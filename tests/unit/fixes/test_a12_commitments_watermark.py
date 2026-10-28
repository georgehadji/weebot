"""A12: commitments are extracted once per event, and the table keeps one row per promise.

The ids were made idempotent first (test_a27_12_commitments_are_idempotent.py). Left
open: every save still re-ran the extractor over every event of the session, rows saved
before the ids were deterministic stayed duplicated, and nothing in the schema stopped a
second row for the same promise.
"""

from __future__ import annotations

import pathlib
import tempfile

import aiosqlite

from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session
from weebot.domain.services import commitment_extractor
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

# The commitments table as it stood before the unique index.
_OLD_TABLE = """
CREATE TABLE commitments (
    id TEXT PRIMARY KEY,
    promise_text TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    source_session_id TEXT NOT NULL,
    source_event_id TEXT,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    failure_reason TEXT
)
"""


def _db() -> str:
    return str(pathlib.Path(tempfile.mkdtemp()) / "s.db")


def _say(session: Session, text: str) -> Session:
    return session.add_event(MessageEvent(role="assistant", message=text))


async def test_a_save_extracts_only_the_events_added_since_the_last_one(monkeypatch):
    seen: list[str] = []
    real = commitment_extractor.extract_commitments

    def spy(text, **kwargs):
        seen.append(text)
        return real(text, **kwargs)

    monkeypatch.setattr(commitment_extractor, "extract_commitments", spy)
    repo = SQLiteStateRepository(db_path=_db())
    session = _say(Session(id="s1", task="t", title="T"), "I'll follow up tomorrow.")
    await repo.save_session(session)
    await repo.save_session(_say(session, "I will send the report on Friday."))
    assert seen == ["I'll follow up tomorrow.", "I will send the report on Friday."]


async def test_old_duplicates_collapse_to_one_row_keeping_the_advanced_status():
    db = _db()
    async with aiosqlite.connect(db) as conn:
        await conn.execute(_OLD_TABLE)
        for i, (status, created) in enumerate(
            [("pending", "2026-01-01"), ("fulfilled", "2026-01-02"), ("pending", "2026-01-03")]
        ):
            await conn.execute(
                "INSERT INTO commitments (id, promise_text, source_session_id, source_event_id,"
                " status, created_at, updated_at) VALUES (?, 'follow up', 's1', 'e1', ?, ?, ?)",
                (f"old-{i}", status, created, created),
            )
        await conn.commit()

    repo = SQLiteStateRepository(db_path=db)
    await repo.save_session(Session(id="other", task="t", title="T"))

    async with aiosqlite.connect(db) as conn:
        rows = await (await conn.execute("SELECT id, status FROM commitments")).fetchall()
    assert rows == [("old-1", "fulfilled")]


async def test_the_table_refuses_a_second_row_for_the_same_promise():
    db = _db()
    repo = SQLiteStateRepository(db_path=db)
    await repo.save_session(Session(id="s1", task="t", title="T"))
    async with aiosqlite.connect(db) as conn:
        rows = await (
            await conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'commitments'"
                " AND sql LIKE '%UNIQUE%'"
            )
        ).fetchall()
    assert rows, "no unique index on the commitments natural key"


def test_an_alembic_migration_adds_the_unique_index():
    versions = pathlib.Path("alembic/versions")
    texts = [p.read_text(encoding="utf-8") for p in versions.glob("*.py")]
    assert any("uq_commitments_natural_key" in t and "b0b1merge0001" in t for t in texts)


def test_the_migration_collapses_duplicates_on_a_database(tmp_path):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text

    path = next(pathlib.Path("alembic/versions").glob("f2c0mm1t0001_*.py"))
    spec = importlib.util.spec_from_file_location("mig", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text(_OLD_TABLE))
        for i, status in enumerate(["pending", "done", "pending"]):
            conn.execute(text(
                "INSERT INTO commitments (id, promise_text, source_session_id, source_event_id,"
                f" status, created_at, updated_at) VALUES ('m{i}', 'p', 's', 'e', '{status}',"
                f" '2026-01-0{i + 1}', '2026-01-0{i + 1}')"
            ))
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
        rows = conn.execute(text("SELECT id FROM commitments")).fetchall()
    assert rows == [("m1",)]
