"""L1 (remaining-work plan 2026-10-29): deleting a session leaves nothing of it behind.

A delete removed the session row but kept its side-constraints and output corrections
(user text in ``evidence_span`` and ``original_output``), its trajectories and failure
signatures (which kept feeding skill optimisation), and any queued steering message.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from weebot.domain.models.correction import CorrectionRecord
from weebot.domain.models.failure_signature import FailureSignature
from weebot.domain.models.session import Session
from weebot.domain.models.session_constraint import SessionConstraint
from weebot.domain.models.trajectory import TrajectorySummary
from weebot.infrastructure.adapters.steering_adapter import InMemorySteeringAdapter
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository


async def _rows(pool, table: str, sid: str) -> int:
    rows = await pool.execute_read(f"SELECT COUNT(*) FROM {table} WHERE session_id = ?", (sid,))
    return rows[0][0]


async def test_the_state_repo_drops_constraints_and_corrections(tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    try:
        for sid in ("gone", "kept"):
            await repo.save_session(Session(id=sid, user_id="u", agent_id="a"))
            await repo.save_session_constraint(sid, SessionConstraint(text="no emails"))
            await repo.save_correction_record(
                CorrectionRecord(
                    session_id=sid, step_id="1", step_description="d",
                    original_output="secret draft", corrected_output="x",
                    correction_category="tone",
                )
            )
        await repo.delete_session("gone")
        pool = await repo._get_pool()
        for table in ("session_constraints", "correction_records"):
            assert await _rows(pool, table, "gone") == 0, table
            assert await _rows(pool, table, "kept") == 1, table
    finally:
        await repo.close()


async def test_the_trajectory_repo_drops_trajectories_and_signatures(tmp_path):
    repo = TrajectoryRepository(db_path=str(tmp_path / "t.db"))
    try:
        for sid in ("gone", "kept"):
            await repo.save(TrajectorySummary(task_id="t", session_id=sid, score=0.5))
            await repo.save_failure_signature(
                FailureSignature(
                    session_id=sid, task_id="t", terminal_cause="c",
                    agent_behavior="b", mechanism="m",
                )
            )
        await repo.delete_by_session_id("gone")
        pool = await repo._get_pool()
        for table in ("trajectories", "failure_signatures"):
            assert await _rows(pool, table, "gone") == 0, table
            assert await _rows(pool, table, "kept") == 1, table
    finally:
        await repo.close()


async def test_steering_drops_the_queued_message():
    steering = InMemorySteeringAdapter()
    await steering.send("gone", "also email bob")
    await steering.send("kept", "hi")
    await steering.discard("gone")
    assert await steering.poll("gone") is None
    assert await steering.poll("kept") == "hi"


async def test_postgres_drops_constraints_and_corrections_with_the_session():
    from weebot.infrastructure.persistence.postgresql.state_repo import (
        PostgreSQLStateRepository,
    )

    executed: list[str] = []

    class _Conn:
        async def execute(self, sql, *args):
            executed.append(sql.split(" WHERE")[0])

        def transaction(self):
            @asynccontextmanager
            async def _tx():
                yield

            return _tx()

    class _Pool:
        @asynccontextmanager
        async def acquire(self):
            yield _Conn()

    repo = PostgreSQLStateRepository()

    async def _pool():
        return _Pool()

    repo._pool = _pool
    await repo.delete_session("gone")
    assert executed == [
        "DELETE FROM session_constraints",
        "DELETE FROM correction_records",
        "DELETE FROM sessions",
    ]
