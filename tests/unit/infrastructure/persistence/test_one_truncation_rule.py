"""The events_json byte ceiling is one rule with one implementation.

D34. `SQLiteStateRepository.save_session` ran a truncation loop identical to the
one in `SessionQueries.save`, and then discarded its result — it passes the
`Session`, not the trimmed list, so the ceiling was applied twice from the same
original events. The dead copy also called `self._fts5_indexed.pop(...)` on each
iteration, resetting the FTS watermark, so every save of an over-ceiling session
re-indexed all of its events into `event_fts`.

Measured before the fix, on a 12-event session held over a 3000-byte ceiling:
`event_fts` grew 12 -> 24 -> 36 rows across three saves of the same unchanged
session, and one save logged 14 truncation warnings for 7 dropped events. A
`search_history` call with limit=10 would have been filled with copies.
"""

from __future__ import annotations

import json
import logging

import aiosqlite
import pytest

import weebot.config.constants as consts
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


@pytest.fixture
def tiny_ceiling(monkeypatch):
    """Lower the ceiling instead of inflating the fixture.

    Both call sites import MAX_EVENTS_JSON_BYTES *inside* the function, so
    patching the module attribute reaches them.
    """
    monkeypatch.setattr(consts, "MAX_EVENTS_JSON_BYTES", 3000)
    return 3000


def _oversized_session() -> Session:
    session = Session(id="s1", task="t", title="T")
    for i in range(12):
        session = session.add_event(MessageEvent(role="assistant", message=f"{i}:" + "x" * 400))
    return session


async def _fts_rows(db_path: str, session_id: str) -> int:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM event_fts WHERE session_id = ?", (session_id,)
        )
        return (await cur.fetchone())[0]


async def _row_event_count(db_path: str, session_id: str) -> int:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute("SELECT events_json FROM sessions WHERE id = ?", (session_id,))
        return len(json.loads((await cur.fetchone())[0]))


@pytest.mark.asyncio
async def test_resaving_an_oversized_session_does_not_grow_the_search_index(
    tmp_path, tiny_ceiling
):
    db = str(tmp_path / "s.db")
    repo = SQLiteStateRepository(db_path=db)
    session = _oversized_session()
    try:
        await repo.save_session(session)
        first = await _fts_rows(db, "s1")
        assert first == 12, "every event should be indexed once"

        await repo.save_session(session)
        await repo.save_session(session)

        assert await _fts_rows(db, "s1") == first, (
            "re-saving an unchanged session re-indexed its events: the truncation "
            "loop reset the FTS watermark, so search returns duplicates and the "
            "index grows without bound"
        )
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_the_ceiling_still_trims_the_row(tmp_path, tiny_ceiling):
    """Removing the duplicate must not remove the rule."""
    db = str(tmp_path / "s.db")
    repo = SQLiteStateRepository(db_path=db)
    session = _oversized_session()
    try:
        await repo.save_session(session)
        persisted = await _row_event_count(db, "s1")
        assert persisted < len(session.events), "the byte ceiling was not applied"
        assert persisted >= 1, "truncation must never empty the row"
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_one_truncation_is_reported_once(tmp_path, tiny_ceiling, caplog):
    """Two implementations logged the same drop twice, under two module names."""
    db = str(tmp_path / "s.db")
    repo = SQLiteStateRepository(db_path=db)
    session = _oversized_session()
    try:
        with caplog.at_level(logging.WARNING):
            await repo.save_session(session)
        truncation_warnings = [r for r in caplog.records if "dropped the" in r.getMessage()]
        assert len(truncation_warnings) == 1, (
            f"expected one warning describing the whole truncation, got "
            f"{len(truncation_warnings)} from {sorted({r.name for r in truncation_warnings})}"
        )
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_save_reports_what_it_dropped(tmp_path, tiny_ceiling):
    """The count is returned, so the caller need not recompute the rule to know."""
    db = str(tmp_path / "s.db")
    repo = SQLiteStateRepository(db_path=db)
    try:
        await repo._init_helpers()
        session = _oversized_session()
        dropped = await repo._session_queries.save(session)
        assert dropped > 0
        assert dropped == len(session.events) - await _row_event_count(db, "s1")

        small = Session(id="s2", task="t", title="T").add_event(
            MessageEvent(role="assistant", message="short")
        )
        assert await repo._session_queries.save(small) == 0
    finally:
        await repo.close()
