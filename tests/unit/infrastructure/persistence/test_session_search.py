"""Session search v2 (H15): substring and non-Latin queries, FTS syntax, scroll, restart."""

from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio

from weebot.application.ports.session_search_port import SessionSearchError
from weebot.domain.models.event import MessageEvent, ToolEvent
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence import fts5_search, sqlite_state_repo
from weebot.infrastructure.persistence.session_search_sqlite import (
    QueryPlan,
    SqliteSessionSearch,
    plan_query,
)
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
from weebot.tools.search_history import SearchHistoryTool


def _session(sid: str, *messages: str) -> Session:
    session = Session(id=sid, task="t", title="T")
    for message in messages:
        session = session.add_event(MessageEvent(role="assistant", message=message))
    return session


@pytest_asyncio.fixture
async def indexed(tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    await repo.save_session(_session("s-config", "edited the config file", "unrelated words"))
    await repo.save_session(_session("s-greek", "η ρύθμιση του συστήματος άλλαξε"))
    await repo.save_session(_session("s-cjk", "更新了配置文件的内容"))
    await repo.save_session(_session("s-alpha", "alpha only"))
    await repo.save_session(_session("s-beta", "beta only"))
    yield repo, SqliteSessionSearch(repo._get_pool)
    await repo.close()


class TestPlanQuery:
    def test_latin_words_go_to_both_indexes(self):
        assert plan_query("config file") == QueryPlan(
            word='"config" AND "file"', substring='"config" AND "file"'
        )

    def test_short_latin_words_stay_in_the_word_index_only(self):
        assert plan_query("go") == QueryPlan(word='"go"', substring="")

    def test_non_latin_goes_to_the_substring_index_only(self):
        assert plan_query("配置文件") == QueryPlan(word="", substring='"配置文件"')

    def test_fts_syntax_passes_through_to_the_word_index(self):
        assert plan_query("a OR b", "fts") == QueryPlan(word="a OR b")

    def test_text_syntax_quotes_operators(self):
        assert plan_query('a OR "b').word == '"a" AND "OR" AND """b"'


@pytest.mark.asyncio
async def test_a_substring_finds_the_word(indexed):
    _, search = indexed

    found = await search.discover("onfig")

    assert [r["session_id"] for r in found] == ["s-config"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "session_id"), [("ρύθμιση", "s-greek"), ("配置文件", "s-cjk")])
async def test_non_latin_queries_find_their_session(indexed, query, session_id):
    _, search = indexed

    assert [r["session_id"] for r in await search.discover(query)] == [session_id]


@pytest.mark.asyncio
async def test_fts_syntax_runs_operators_and_text_syntax_does_not(indexed):
    _, search = indexed

    with_fts = await search.discover("alpha OR beta", syntax="fts")
    as_text = await search.discover("alpha OR beta", syntax="text")

    assert {r["session_id"] for r in with_fts} == {"s-alpha", "s-beta"}
    assert as_text == []


@pytest.mark.asyncio
async def test_a_malformed_fts_query_is_a_search_error(indexed):
    _, search = indexed

    with pytest.raises(SessionSearchError):
        await search.discover('"unterminated', syntax="fts")


@pytest.mark.asyncio
async def test_discover_returns_one_row_per_session_with_its_hit_count(tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    try:
        await repo.save_session(_session("s1", "deploy one", "deploy two", "other"))
        found = await SqliteSessionSearch(repo._get_pool).discover("deploy")
    finally:
        await repo.close()

    assert len(found) == 1 and found[0]["hits"] == 2 and 0 <= found[0]["score"] < 1


@pytest.mark.asyncio
async def test_scroll_returns_the_events_around_a_hit_in_order(tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    try:
        await repo.save_session(_session("s1", *(f"step {i}" for i in range(9))))
        await repo.save_session(_session("s2", "step interleaved"))
        search = SqliteSessionSearch(repo._get_pool)
        hit = next(r for r in await search.discover("step 4") if r["session_id"] == "s1")

        around = await search.scroll("s1", hit["event_id"], window=2)
    finally:
        await repo.close()

    assert [e["summary"] for e in around] == ["step 2", "step 3", "step 4", "step 5", "step 6"]
    assert [e["target"] for e in around] == [False, False, True, False, False]


@pytest.mark.asyncio
async def test_read_returns_one_event_and_none_for_an_unknown_id(indexed):
    _, search = indexed
    hit = (await search.discover("onfig"))[0]

    event = await search.read(hit["event_id"])

    assert event is not None and event["summary"] == "edited the config file"
    assert event["ts"]
    assert await search.read("no-such-event") is None


@pytest.mark.asyncio
async def test_tool_results_stay_out_of_the_trigram_index(tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    try:
        session = _session("s1", "a message")
        session = session.add_event(ToolEvent(tool_name="bash", result="x" * 50))
        await repo.save_session(session)
        pool = await repo._get_pool()
        words = await pool.execute_read("SELECT COUNT(*) AS n FROM event_fts")
        grams = await pool.execute_read("SELECT COUNT(*) AS n FROM event_fts_trigram")
    finally:
        await repo.close()

    assert (words[0]["n"], grams[0]["n"]) == (2, 1)


@pytest.mark.asyncio
async def test_a_restart_does_not_index_a_session_again(tmp_path, monkeypatch):
    db = str(tmp_path / "s.db")
    first = SQLiteStateRepository(db_path=db)
    try:
        await first.save_session(_session("s1", "one", "two", "three"))
    finally:
        await first.close()

    calls = []
    real = fts5_search.index_event

    async def counting(conn, session_id, event_type, summary, *args, **kwargs):
        calls.append(summary)
        return await real(conn, session_id, event_type, summary, *args, **kwargs)

    monkeypatch.setattr(sqlite_state_repo, "index_event", counting)
    second = SQLiteStateRepository(db_path=db)
    try:
        loaded = await second.load_session("s1")
        await second.save_session(loaded)
        await second.save_session(
            loaded.add_event(MessageEvent(role="assistant", message="four"))
        )
    finally:
        await second.close()

    assert calls == ["four"], "only the one new event is indexed after a restart"


@pytest.mark.asyncio
async def test_a_table_without_event_ids_is_rebuilt_and_re_indexed_on_the_next_save(tmp_path):
    db = str(tmp_path / "s.db")
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "CREATE VIRTUAL TABLE event_fts USING fts5("
            "session_id UNINDEXED, event_type, summary, content, tokenize='porter unicode61')"
        )
        await conn.execute(
            "INSERT INTO event_fts(session_id, event_type, summary, content) "
            "VALUES ('s1', 'message', 'old row', '')"
        )
        await conn.commit()

    repo = SQLiteStateRepository(db_path=db)
    try:
        await repo.save_session(_session("s1", "fresh row"))
        found = await SqliteSessionSearch(repo._get_pool).discover("row")
    finally:
        await repo.close()

    assert [(r["summary"], r["hits"]) for r in found] == [("fresh row", 1)]


@pytest.mark.asyncio
async def test_deleting_a_session_removes_its_entries_and_watermark(tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    try:
        await repo.save_session(_session("s1", "findable text"))
        await repo.delete_session("s1")
        pool = await repo._get_pool()
        left = await pool.execute_read("SELECT COUNT(*) AS n FROM fts_watermark")
        found = await SqliteSessionSearch(repo._get_pool).discover("findable")
    finally:
        await repo.close()

    assert left[0]["n"] == 0 and found == []


class _FakePort:
    def __init__(self):
        self.calls = []

    async def discover(self, query, limit=10, syntax="text"):
        self.calls.append(("discover", query, limit, syntax))
        return []

    async def scroll(self, session_id, around_event_id, window=5):
        self.calls.append(("scroll", session_id, around_event_id, window))
        return []

    async def read(self, event_id):
        self.calls.append(("read", event_id))
        return None


@pytest.mark.asyncio
async def test_the_tool_routes_each_mode_to_the_port():
    port = _FakePort()
    tool = SearchHistoryTool(search=port)

    await tool.execute(query="x", syntax="fts", limit=500)
    scrolled = await tool.execute(mode="scroll", session_id="s", event_id="e", window=3)
    read = await tool.execute(mode="read", event_id="e")

    assert port.calls == [
        ("discover", "x", 50, "fts"),
        ("scroll", "s", "e", 3),
        ("read", "e"),
    ]
    assert not scrolled.success and not read.success


@pytest.mark.asyncio
async def test_the_tool_reports_a_bad_query_and_missing_arguments():
    class Failing(_FakePort):
        async def discover(self, *a, **k):
            raise SessionSearchError("invalid FTS5 query")

    tool = SearchHistoryTool(search=Failing())

    assert "invalid FTS5 query" in (await tool.execute(query="x", syntax="fts")).error
    assert not (await tool.execute(query="  ")).success
    assert not (await tool.execute(mode="scroll", session_id="s")).success
    assert not (await tool.execute(mode="bogus")).success
