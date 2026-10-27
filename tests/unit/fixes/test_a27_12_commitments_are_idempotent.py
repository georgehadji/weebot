"""A12: each save_session re-extracted every promise under a fresh uuid4, so rows multiplied."""

from __future__ import annotations

import pathlib
import tempfile

import aiosqlite

from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session
from weebot.domain.services.commitment_extractor import extract_commitments
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


def _repo():
    db = str(pathlib.Path(tempfile.mkdtemp()) / "s.db")
    return SQLiteStateRepository(db_path=db), db


def _session() -> Session:
    s = Session(id="sess-1", task="t", title="T")
    return s.add_event(MessageEvent(role="assistant", message="I'll follow up with you tomorrow."))


async def _rows(db):
    async with aiosqlite.connect(db) as conn:
        return await (await conn.execute("SELECT id, status FROM commitments")).fetchall()


def test_the_same_promise_gets_the_same_id():
    a = extract_commitments("I'll follow up tomorrow.", source_session_id="s", source_event_id="e1")
    b = extract_commitments("I'll follow up tomorrow.", source_session_id="s", source_event_id="e1")
    assert a and [c.id for c in a] == [c.id for c in b]


def test_the_same_promise_in_another_event_gets_another_id():
    a = extract_commitments("I'll follow up tomorrow.", source_session_id="s", source_event_id="e1")
    b = extract_commitments("I'll follow up tomorrow.", source_session_id="s", source_event_id="e2")
    assert a[0].id != b[0].id


async def test_saving_the_same_session_three_times_keeps_one_row():
    repo, db = _repo()
    session = _session()
    for _ in range(3):
        await repo.save_session(session)
    assert len(await _rows(db)) == 1


async def test_a_resave_does_not_reset_a_fulfilled_commitment():
    repo, db = _repo()
    session = _session()
    await repo.save_session(session)
    (commitment_id, _), = await _rows(db)
    await repo.update_commitment_status(commitment_id, "fulfilled")
    await repo.save_session(session)
    assert await _rows(db) == [(commitment_id, "fulfilled")]
