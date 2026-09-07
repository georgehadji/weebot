"""Indexing the same session twice must not double its entries in search.

D71. `_fts5_indexed` is a plain dict on the repository instance — nothing
persists it. So the first `save_session` performed by a fresh repository always
starts from watermark zero and re-walks every event, and `index_event` only ever
INSERTs. Every process restart therefore added another full copy of every
session it touched to `event_fts`.

Measured before the fix: a 6-event session indexed by one repository reached 12
rows after a second repository loaded and saved it — and would have kept
climbing, one full copy per restart. `search_history` returns a fixed-size
window ranked by relevance, so N copies of one event crowd out N-1 other
results.

The fix makes a full re-index REPLACE a session's entries instead of appending
to them. `test_a_full_reindex_drops_entries_the_row_no_longer_carries` pins the
cost that buys.
"""

from __future__ import annotations

import aiosqlite
import pytest

import weebot.config.constants as consts
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


async def _fts_rows(db_path: str, session_id: str) -> int:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM event_fts WHERE session_id = ?", (session_id,)
        )
        return (await cur.fetchone())[0]


def _session(n: int = 6, sid: str = "s1") -> Session:
    session = Session(id=sid, task="t", title="T")
    for i in range(n):
        session = session.add_event(MessageEvent(role="assistant", message=f"event number {i}"))
    return session


@pytest.mark.asyncio
async def test_a_second_repository_does_not_double_the_index(tmp_path):
    """The restart case: a fresh instance has no watermark and re-indexes."""
    db = str(tmp_path / "s.db")

    first = SQLiteStateRepository(db_path=db)
    try:
        await first.save_session(_session())
        after_first = await _fts_rows(db, "s1")
        assert after_first == 6
    finally:
        await first.close()

    second = SQLiteStateRepository(db_path=db)
    try:
        loaded = await second.load_session("s1")
        assert loaded is not None and len(loaded.events) == 6
        await second.save_session(loaded)
        assert await _fts_rows(db, "s1") == after_first, (
            "a fresh repository re-indexed the whole session on top of the entries "
            "the previous one wrote: the index grows by a full copy per restart"
        )
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_repeated_restarts_do_not_accumulate(tmp_path):
    """Three restarts, one copy — not three."""
    db = str(tmp_path / "s.db")
    session = _session()
    for _ in range(3):
        repo = SQLiteStateRepository(db_path=db)
        try:
            await repo.save_session(session)
        finally:
            await repo.close()
    assert await _fts_rows(db, "s1") == 6


@pytest.mark.asyncio
async def test_incremental_indexing_still_only_indexes_new_events(tmp_path):
    """Replacing on a cold watermark must not turn every save into a full rewrite."""
    db = str(tmp_path / "s.db")
    repo = SQLiteStateRepository(db_path=db)
    try:
        session = _session(3)
        await repo.save_session(session)
        assert await _fts_rows(db, "s1") == 3

        for i in range(3, 6):
            session = session.add_event(
                MessageEvent(role="assistant", message=f"event number {i}")
            )
        await repo.save_session(session)
        assert await _fts_rows(db, "s1") == 6, "appended events should be indexed once each"
        assert repo._fts5_indexed["s1"] == 6
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_search_returns_one_hit_per_event_after_a_restart(tmp_path):
    """The user-visible consequence, stated in the tool's own terms."""
    db = str(tmp_path / "s.db")
    session = _session(4)
    for repo_n in range(3):
        repo = SQLiteStateRepository(db_path=db)
        try:
            await repo.save_session(session)
            hits = await repo.search_sessions("event", limit=50)
        finally:
            await repo.close()
    assert len(hits) == 4, f"one hit per event expected, got {len(hits)} after {repo_n + 1} restarts"


@pytest.mark.asyncio
async def test_a_full_reindex_drops_entries_the_row_no_longer_carries(tmp_path, monkeypatch):
    """The accepted cost, pinned so it is a decision and not a surprise.

    Truncated events survive in the index only as long as the watermark that
    knows about them — i.e. the life of the repository instance. A restart
    reloads the truncated row and the index converges on it.
    """
    monkeypatch.setattr(consts, "MAX_EVENTS_JSON_BYTES", 3000)
    db = str(tmp_path / "s.db")
    session = Session(id="s1", task="t", title="T")
    for i in range(12):
        session = session.add_event(MessageEvent(role="assistant", message=f"{i}:" + "x" * 400))

    first = SQLiteStateRepository(db_path=db)
    try:
        await first.save_session(session)
        assert await _fts_rows(db, "s1") == 12, "in-process, the index keeps the dropped events"
    finally:
        await first.close()

    second = SQLiteStateRepository(db_path=db)
    try:
        loaded = await second.load_session("s1")
        await second.save_session(loaded)
        assert await _fts_rows(db, "s1") == len(loaded.events) < 12
    finally:
        await second.close()
