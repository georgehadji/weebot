"""Trajectory repository — reads and writes TrajectorySummary rows.

Also stores FailureSignature rows for the Self-Harness Weakness Mining
stage.  Uses the same SQLite connection pool as SQLiteStateRepository
to avoid a second database connection.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from weebot.application.ports.event_store_port import EventStorePort
from weebot.domain.models.failure_signature import (
    EvidenceBundle,
    FailureCluster,
    FailureSignature,
)
from weebot.domain.models.trajectory import TrajectorySummary, TrajectoryHealth
from weebot.application.ports.trajectory_repository_port import TrajectoryRepositoryPort
from weebot.infrastructure.persistence.connection_pool import (
    get_or_create_pool,
)

logger = logging.getLogger(__name__)


class TrajectoryRepository(TrajectoryRepositoryPort):
    """SQLite adapter for TrajectoryRepositoryPort."""

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

        await self._ensure_failure_signatures_schema(pool)

    async def _ensure_failure_signatures_schema(self, pool) -> None:
        """Create the failure_signatures table and indices."""
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS failure_signatures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL DEFAULT '',
                    terminal_cause TEXT NOT NULL DEFAULT '',
                    agent_behavior TEXT NOT NULL DEFAULT '',
                    mechanism TEXT NOT NULL DEFAULT '',
                    trajectory_health TEXT,
                    actionability_score REAL NOT NULL DEFAULT 0.0,
                    harness_version TEXT NOT NULL DEFAULT '',
                    model_id TEXT NOT NULL DEFAULT '',
                    extracted_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fs_session
                ON failure_signatures(session_id)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fs_cluster
                ON failure_signatures(terminal_cause, agent_behavior, mechanism)
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fs_lookback
                ON failure_signatures(extracted_at)
                """
            )
            logger.debug("Failure signatures table schema ensured")

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

    # ── Failure Signature CRUD ───────────────────────────────────────────

    async def save_failure_signature(self, signature: FailureSignature) -> None:
        """Persist a failure signature for clustering.

        Uses INSERT OR IGNORE to prevent duplicate signatures for the
        same session.  The UNIQUE constraint on session_id ensures each
        session produces at most one signature.
        """
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO failure_signatures
                    (session_id, task_id, terminal_cause, agent_behavior, mechanism,
                     trajectory_health, actionability_score, harness_version, model_id,
                     extracted_at)
                VALUES
                    (:session_id, :task_id, :terminal_cause, :agent_behavior, :mechanism,
                     :trajectory_health, :actionability_score, :harness_version, :model_id,
                     :extracted_at)
                """,
                {
                    "session_id": signature.session_id,
                    "task_id": signature.task_id,
                    "terminal_cause": signature.terminal_cause,
                    "agent_behavior": signature.agent_behavior,
                    "mechanism": signature.mechanism,
                    "trajectory_health": signature.trajectory_health.value if signature.trajectory_health else None,
                    "actionability_score": signature.actionability_score,
                    "harness_version": signature.harness_version,
                    "model_id": signature.model_id,
                    "extracted_at": signature.extracted_at.isoformat(),
                },
            )

    async def get_clusters(
        self,
        min_support: int = 3,
        lookback_days: int = 7,
        max_clusters: int = 5,
        harness_version: str | None = None,
        model_id: str | None = None,
    ) -> list[FailureCluster]:
        """Group failure signatures into clusters by exact signature match.

        Returns clusters ordered by (count × mean_actionability) descending.
        """
        pool = await self._get_pool()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        where_clauses = ["extracted_at >= :cutoff"]
        params: dict[str, object] = {"cutoff": cutoff}

        if harness_version:
            where_clauses.append("harness_version = :harness_version")
            params["harness_version"] = harness_version
        if model_id:
            where_clauses.append("model_id = :model_id")
            params["model_id"] = model_id

        where_sql = " AND ".join(where_clauses)

        rows = await pool.execute_read(
            f"""
            SELECT terminal_cause, agent_behavior, mechanism,
                   COUNT(*) as support,
                   AVG(actionability_score) as avg_actionability,
                   GROUP_CONCAT(session_id) as all_sessions
            FROM failure_signatures
            WHERE {where_sql}
            GROUP BY terminal_cause, agent_behavior, mechanism
            HAVING support >= :min_support
            ORDER BY support * AVG(actionability_score) DESC
            LIMIT :limit
            """,
            {**params, "min_support": min_support, "limit": max_clusters},
        )

        if not rows:
            return []

        clusters = []
        for row in rows:
            session_ids = (row["all_sessions"] or "").split(",")
            rep_sig = FailureSignature(
                session_id=session_ids[0] if session_ids else "",
                task_id="",
                terminal_cause=row["terminal_cause"],
                agent_behavior=row["agent_behavior"],
                mechanism=row["mechanism"],
                actionability_score=row["avg_actionability"],
            )
            clusters.append(
                FailureCluster(
                    signature=rep_sig,
                    support=row["support"],
                    representative_session_ids=session_ids[:5],
                    mean_actionability=row["avg_actionability"],
                )
            )

        return clusters

    async def count_trajectories(
        self, lookback_days: int = 7,
    ) -> int:
        """Count total trajectories within the lookback window."""
        pool = await self._get_pool()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        rows = await pool.execute_read(
            "SELECT COUNT(*) as cnt FROM trajectories WHERE created_at >= ?",
            (cutoff,),
        )
        return rows[0]["cnt"] if rows else 0

    async def get_sessions_without_signature(
        self,
        lookback_days: int = 7,
        max_sessions: int = 200,
        force_reprocess: bool = False,
    ) -> list[tuple[str, str | None, str | None, str | None]]:
        """Return (session_id, task_id, trajectory_text, failure_modes_json)
        for trajectories that lack a failure_signature entry.

        Used by BatchExtractSignaturesHandler for bootstrapping.
        """
        pool = await self._get_pool()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        if force_reprocess:
            rows = await pool.execute_read(
                """
                SELECT t.session_id, t.task_id, t.trajectory_text, t.failure_modes
                FROM trajectories t
                WHERE t.created_at >= :cutoff
                  AND t.passed = 0
                ORDER BY t.created_at DESC
                LIMIT :limit
                """,
                {"cutoff": cutoff, "limit": max_sessions},
            )
        else:
            rows = await pool.execute_read(
                """
                SELECT t.session_id, t.task_id, t.trajectory_text, t.failure_modes
                FROM trajectories t
                LEFT JOIN failure_signatures fs ON t.session_id = fs.session_id
                WHERE t.created_at >= :cutoff
                  AND t.passed = 0
                  AND fs.session_id IS NULL
                ORDER BY t.created_at DESC
                LIMIT :limit
                """,
                {"cutoff": cutoff, "limit": max_sessions},
            )
        return [
            (r["session_id"], r["task_id"], r["trajectory_text"], r["failure_modes"])
            for r in rows
        ]

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
