"""Trajectory repository — reads and writes TrajectorySummary rows.

Uses the same SQLite connection pool as SQLiteStateRepository to avoid
a second database connection.  In tests, this can be replaced with an
in-memory adapter.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from weebot.application.ports.event_store_port import EventStorePort
from weebot.domain.models.trajectory import TrajectorySummary
from weebot.infrastructure.persistence.connection_pool import (
    get_or_create_pool,
)

logger = logging.getLogger(__name__)


class TrajectoryRepository:
    """Persistence for trajectory evidence.

    Stores trajectories in a separate table alongside the existing
    event store.  One trajectory per completed task execution.
    """

    def __init__(self, db_path: str = "./weebot_sessions.db"):
        self._db_path = Path(db_path)
        self._pool = None
        self._initialized = False

    async def _get_pool(self):
        if self._pool is None:
            self._pool = await get_or_create_pool(
                self._db_path,
                max_read_connections=5,
                enable_wal=True,
            )
            if not self._initialized:
                await self._ensure_schema()
                self._initialized = True
        return self._pool

    async def _ensure_schema(self):
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trajectories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL DEFAULT '',
                    skill_version INTEGER NOT NULL DEFAULT 0,
                    harness TEXT NOT NULL DEFAULT 'direct_chat',
                    score REAL NOT NULL DEFAULT 0.0,
                    passed INTEGER NOT NULL DEFAULT 0,
                    failure_modes TEXT NOT NULL DEFAULT '[]',
                    success_patterns TEXT NOT NULL DEFAULT '[]',
                    tool_call_count INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    total_cost REAL NOT NULL DEFAULT 0.0,
                    trajectory_text TEXT NOT NULL DEFAULT '',
                    answer TEXT,
                    expected_answer TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trajectories_skill
                ON trajectories(skill_name, skill_version)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trajectories_session
                ON trajectories(session_id)
                """
            )
            logger.debug("Trajectory table schema ensured")

    async def save(self, trajectory: TrajectorySummary) -> None:
        """Persist a single trajectory."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO trajectories
                    (task_id, session_id, skill_name, skill_version, harness,
                     score, passed, failure_modes, success_patterns,
                     tool_call_count, total_tokens, total_cost,
                     trajectory_text, answer, expected_answer, created_at)
                VALUES
                    (:task_id, :session_id, :skill_name, :skill_version, :harness,
                     :score, :passed, :failure_modes, :success_patterns,
                     :tool_call_count, :total_tokens, :total_cost,
                     :trajectory_text, :answer, :expected_answer, :created_at)
                """,
                {
                    "task_id": trajectory.task_id,
                    "session_id": trajectory.session_id,
                    "skill_name": trajectory.skill_name,
                    "skill_version": trajectory.skill_version,
                    "harness": trajectory.harness,
                    "score": trajectory.score,
                    "passed": int(trajectory.passed),
                    "failure_modes": json.dumps(trajectory.failure_modes),
                    "success_patterns": json.dumps(trajectory.success_patterns),
                    "tool_call_count": trajectory.tool_call_count,
                    "total_tokens": trajectory.total_tokens,
                    "total_cost": trajectory.total_cost,
                    "trajectory_text": trajectory.trajectory_text,
                    "answer": trajectory.answer,
                    "expected_answer": trajectory.expected_answer,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    async def get_by_skill(
        self,
        skill_name: str,
        skill_version: int,
        limit: int = 200,
    ) -> list[TrajectorySummary]:
        """Retrieve trajectories for a specific skill version."""
        pool = await self._get_pool()
        rows = await pool.execute_read(
            """
            SELECT * FROM trajectories
            WHERE skill_name = ? AND skill_version = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (skill_name, skill_version, limit),
        )
        return [self._row_to_trajectory(r) for r in rows]

    async def get_by_session(
        self, session_id: str
    ) -> list[TrajectorySummary]:
        """Retrieve all trajectories for a session."""
        pool = await self._get_pool()
        rows = await pool.execute_read(
            """
            SELECT * FROM trajectories
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        return [self._row_to_trajectory(r) for r in rows]

    @staticmethod
    def _row_to_trajectory(row) -> TrajectorySummary:
        return TrajectorySummary(
            task_id=row["task_id"],
            session_id=row["session_id"],
            skill_name=row["skill_name"],
            skill_version=row["skill_version"],
            harness=row["harness"],
            score=row["score"],
            passed=bool(row["passed"]),
            failure_modes=json.loads(row["failure_modes"] or "[]"),
            success_patterns=json.loads(row["success_patterns"] or "[]"),
            tool_call_count=row["tool_call_count"],
            total_tokens=row["total_tokens"],
            total_cost=row["total_cost"],
            trajectory_text=row["trajectory_text"],
            answer=row["answer"],
            expected_answer=row["expected_answer"],
        )

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
