"""D32 — three write transactions, and the first one had never committed.

The record said: "`save_session` spans three separate write transactions; a
crash between them leaves partial state." True, and the measurement found
something the record did not: **transaction 1 raised on every single call.**

    sqlite3.ProgrammingError: Error binding parameter 7:
    type 'CommitmentStatus' is not supported

`CommitmentStatus` was a bare `Enum` while every sibling — `SessionStatus`,
`PlanStatus`, `StepStatus`, `AuditVerdict` — is `str, Enum`. sqlite3 binds a
`str` subclass and refuses a bare one. So `save_commitment` failed for the life
of the feature, and `save_session` wrapped the whole block in

    except Exception as exc:
        logger.debug("Commitment extraction skipped (non-fatal): %s", exc)

at DEBUG. The commitment feature has never persisted a row, and the only trace
was a line nobody reads. Measured: extraction returns 1 commitment for
"I'll follow up with you tomorrow." and the commitments table stays empty.

Three fixes, and the ordering one is the record's actual claim: commitments
carry `source_session_id`, so writing them BEFORE the session row meant a crash
in between left rows pointing at a session that does not exist.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session


def _repo():
    from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

    db = str(pathlib.Path(tempfile.mkdtemp()) / "s.db")
    return SQLiteStateRepository(db_path=db), db


def _session_with_a_promise(session_id: str = "sess-1") -> Session:
    session = Session(id=session_id, task="t", title="T")
    # Matches `_COMMITMENT_PATTERNS`' follow_up rule. Arbitrary promises like
    # "I will write the report" match nothing — the extractor wants specific
    # verbs, which is worth knowing before writing a fixture against it.
    return session.add_event(
        MessageEvent(role="assistant", message="I'll follow up with you tomorrow.")
    )


def test_the_status_enum_is_bindable_by_sqlite():
    """The defect in one line, and the reason it went unnoticed for so long.

    A bare Enum is not a `str`, and sqlite3 refuses to bind it. Every sibling
    status enum in this codebase is a `str, Enum`; this one alone was not.
    """
    from enum import Enum

    from weebot.domain.models.commitment import CommitmentStatus
    from weebot.domain.models.plan import PlanStatus, StepStatus
    from weebot.domain.models.session import SessionStatus

    assert issubclass(CommitmentStatus, str), "sqlite3 cannot bind a bare Enum"
    for sibling in (SessionStatus, PlanStatus, StepStatus):
        assert issubclass(sibling, str) and issubclass(sibling, Enum)


@pytest.mark.asyncio
async def test_a_commitment_actually_reaches_the_database():
    """Nothing had ever been written to this table."""
    import aiosqlite

    repo, db = _repo()
    await repo.save_session(_session_with_a_promise())

    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM commitments")
        assert (await cur.fetchone())[0] == 1, "the commitment did not persist"


@pytest.mark.asyncio
async def test_a_crash_before_the_session_row_leaves_no_orphan():
    """The record's claim, now that transaction 1 can actually write.

    Commitments carry `source_session_id`. Writing them first meant a crash in
    between left rows referencing a session that does not exist. The dependent
    write goes second, so the only reachable partial state is a session with no
    commitments — a missing side-feature, not a dangling reference.

    Passes against the unfixed code too, and for a reason that is the whole
    point: commitments never wrote at ALL there, so there were no orphans to
    find. The ordering only becomes load-bearing now that transaction 1 works.
    """
    import aiosqlite

    repo, db = _repo()
    await repo._init_helpers()

    async def boom(_session):
        raise RuntimeError("crash between the session write and the commitment write")

    repo._session_queries.save = boom
    with pytest.raises(RuntimeError):
        await repo.save_session(_session_with_a_promise("sess-2"))

    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM commitments WHERE source_session_id = 'sess-2'"
        )
        assert (await cur.fetchone())[0] == 0, (
            "commitments were persisted for a session that was never written"
        )


@pytest.mark.asyncio
async def test_a_commitment_failure_does_not_lose_the_session(caplog):
    """FAIL OPEN, LOUDLY — the policy from Phase 0, applied here.

    A session must persist even when commitment extraction breaks. But the
    old handler logged at DEBUG, which is how a total feature outage stayed
    invisible. WARNING with the session id, so the next occurrence is findable.
    """
    import logging

    repo, _db = _repo()
    await repo._init_helpers()

    async def boom(_cmt):
        raise RuntimeError("commitment table is gone")

    repo.save_commitment = boom

    caplog.set_level(logging.WARNING, logger="weebot.infrastructure.persistence.sqlite_state_repo")
    await repo.save_session(_session_with_a_promise("sess-3"))

    loaded = await repo.load_session("sess-3")
    assert loaded is not None, "a commitment failure must not lose the session"
    assert "Commitment extraction failed" in caplog.text
    assert "sess-3" in caplog.text


@pytest.mark.asyncio
async def test_a_session_with_no_promises_writes_no_commitments():
    """REGRESSION GUARD: the extractor is pattern-based and must stay narrow.

    "I will write the report tomorrow" matches none of `_COMMITMENT_PATTERNS`
    — the rules want `follow up`, `check back`, `monitor`, `notify`. If this
    starts failing, the patterns have been widened and every assistant message
    is being recorded as a promise.

    Also passes unfixed, for the same reason as above. It earns its place now:
    with the table finally writable, "writes nothing" and "cannot write" are no
    longer the same observation.
    """
    import aiosqlite

    repo, db = _repo()
    session = Session(id="sess-4", task="t", title="T").add_event(
        MessageEvent(role="assistant", message="Here is the report you asked for.")
    )
    await repo.save_session(session)

    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM commitments")
        assert (await cur.fetchone())[0] == 0
