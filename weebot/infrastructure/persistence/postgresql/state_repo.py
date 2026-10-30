"""PostgreSQL state repository — implements StateRepositoryPort via asyncpg.

Requires ``WEEBOT_DB_BACKEND=postgresql`` (and ``WEEBOT_PG_DSN``) to activate.
SQLite remains the default.

The schema is created on first use: ``_ensure_schema`` existed but nothing called
it, so a fresh database had no tables. It also plays every role the SQLite
repository plays (``PostgresRoleStores``), so the learning loops keep working.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from collections.abc import Sequence
from typing import Any

from weebot.application.ports.state_repo_port import SessionActivity, StateRepositoryPort
from weebot.application.ports.state_roles_port import (
    BehavioralRuleStore,
    CommitmentStore,
    CorrectionStore,
    MemoryMetadataStore,
    OpportunityStore,
    PlanTemplateStore,
    PlanTemplateWriter,
    SessionConstraintStore,
    WorkflowTemplateStore,
)
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.postgresql._role_stores import (
    ROLE_SCHEMA,
    PostgresRoleStores,
)
from weebot.infrastructure.persistence.postgresql.connection import get_pool

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT,
    context JSONB NOT NULL DEFAULT '{}',
    search_vector tsvector,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_search ON sessions USING GIN (search_vector);
CREATE TABLE IF NOT EXISTS session_events (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id, idx);
"""

_UPSERT_SESSION = """
INSERT INTO sessions (id, user_id, agent_id, status, title, context, search_vector,
                      created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, to_tsvector('english', $7), $8, $9)
ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status,
    title = EXCLUDED.title,
    context = EXCLUDED.context,
    search_vector = EXCLUDED.search_vector,
    updated_at = EXCLUDED.updated_at
"""


def _search_text(session: Session) -> str:
    """What full-text search indexes: the title and the task."""
    task = session.context.original_task if session.context else ""
    return f"{session.title or ''} {task or ''}"


class PostgreSQLStateRepository(
    PostgresRoleStores,
    StateRepositoryPort,
    BehavioralRuleStore,
    CorrectionStore,
    SessionConstraintStore,
    OpportunityStore,
    MemoryMetadataStore,
    PlanTemplateWriter,
    PlanTemplateStore,
    CommitmentStore,
    WorkflowTemplateStore,
):
    """PostgreSQL-backed session persistence (sessions domain pool)."""

    def __init__(self) -> None:
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def _pool(self) -> Any:
        pool = await get_pool("sessions")
        if not self._schema_ready:
            async with self._schema_lock:
                if not self._schema_ready:
                    async with pool.acquire() as conn:
                        await conn.execute(_SCHEMA)
                        await conn.execute(ROLE_SCHEMA)
                    self._schema_ready = True
        return pool

    async def _ensure_schema(self) -> None:
        await self._pool()

    async def _execute(self, sql: str, *args: Any) -> str:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def _fetch(self, sql: str, *args: Any) -> list[dict]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            return [dict(r) for r in await conn.fetch(sql, *args)]

    # ── Session rows ──────────────────────────────────────────────

    async def _write(self, conn: Any, session: Session) -> None:
        await conn.execute(
            _UPSERT_SESSION,
            session.id,
            session.user_id,
            session.agent_id,
            session.status.value,
            session.title,
            session.context.model_dump(mode="json"),
            _search_text(session),
            session.created_at,
            session.updated_at,
        )
        await conn.execute("DELETE FROM session_events WHERE session_id = $1", session.id)
        if session.events:
            await conn.executemany(
                "INSERT INTO session_events (session_id, idx, event_type, event_data)"
                " VALUES ($1, $2, $3, $4)",
                [
                    (session.id, idx, type(e).__name__, e.model_dump(mode="json"))
                    for idx, e in enumerate(session.events)
                ],
            )

    @staticmethod
    def _to_session(row: Any, events: list | None = None) -> Session:
        data = {k: v for k, v in dict(row).items() if k != "search_vector"}
        data["events"] = events or []
        data["title"] = data.get("title") or ""
        return Session.model_validate(data)

    async def save_session(self, session: Session) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn, conn.transaction():
            await self._write(conn, session)

    async def create_session(self, session: Session) -> bool:
        """Insert *session* unless one with its id exists; True when inserted."""
        pool = await self._pool()
        async with pool.acquire() as conn, conn.transaction():
            created = await conn.fetchval(
                "INSERT INTO sessions (id, user_id, agent_id, status, created_at, updated_at)"
                " VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING RETURNING id",
                session.id,
                session.user_id,
                session.agent_id,
                session.status.value,
                session.created_at,
                session.updated_at,
            )
            if created is None:
                return False
            await self._write(conn, session)
            return True

    async def save_session_if_unchanged(
        self, session: Session, expected_updated_at: datetime
    ) -> bool:
        """Save only if the stored row still has *expected_updated_at* (compare-and-set)."""
        pool = await self._pool()
        async with pool.acquire() as conn, conn.transaction():
            current = await conn.fetchval(
                "SELECT updated_at FROM sessions WHERE id = $1 FOR UPDATE", session.id
            )
            if current is None or current != expected_updated_at:
                return False
            await self._write(conn, session)
            return True

    async def load_session(self, session_id: str) -> Session | None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
            if row is None:
                return None
            events = await conn.fetch(
                "SELECT event_data FROM session_events WHERE session_id = $1 ORDER BY idx",
                session_id,
            )
            return self._to_session(row, [e["event_data"] for e in events])

    async def list_sessions(
        self,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        load_events: bool = False,
    ) -> list:
        conditions: list[str] = []
        params: list[Any] = []
        if user_id:
            params.append(user_id)
            conditions.append(f"user_id = ${len(params)}")
        if status:
            params.append(status)
            conditions.append(f"status = ${len(params)}")
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]
        sql = (
            f"SELECT * FROM sessions{where} ORDER BY updated_at DESC"
            f" LIMIT ${len(params) - 1} OFFSET ${len(params)}"
        )
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            sessions = []
            for r in rows:
                events = None
                if load_events:
                    events = [
                        e["event_data"]
                        for e in await conn.fetch(
                            "SELECT event_data FROM session_events"
                            " WHERE session_id = $1 ORDER BY idx",
                            r["id"],
                        )
                    ]
                sessions.append(self._to_session(r, events))
            return sessions

    async def count_sessions(self, user_id: str | None = None, status: str | None = None) -> int:
        conditions: list[str] = []
        params: list[Any] = []
        if user_id:
            params.append(user_id)
            conditions.append(f"user_id = ${len(params)}")
        if status:
            params.append(status)
            conditions.append(f"status = ${len(params)}")
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        pool = await self._pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(f"SELECT COUNT(*) FROM sessions{where}", *params)  # noqa: S608

    async def session_activity(self, session_ids: Sequence[str]) -> dict[str, SessionActivity]:
        """Two grouped queries over session_events; events are not loaded (R19)."""
        ids = list(dict.fromkeys(session_ids))
        counts: dict[str, dict[tuple[str, str], int]] = {sid: {} for sid in ids}
        plans: dict[str, list[Any]] = {sid: [] for sid in ids}
        pool = await self._pool()
        async with pool.acquire() as conn:
            for r in await conn.fetch(
                "SELECT session_id, event_data->>'type' AS t,"
                " COALESCE(event_data->>'status', '') AS st, COUNT(*) AS n"
                " FROM session_events WHERE session_id = ANY($1::text[]) GROUP BY 1, 2, 3",
                ids,
            ):
                counts[r["session_id"]][(r["t"] or "", r["st"])] = r["n"]
            for r in await conn.fetch(
                "SELECT session_id, event_data FROM session_events"
                " WHERE session_id = ANY($1::text[]) AND event_data->>'type' IN ('plan', 'step')"
                " ORDER BY session_id, idx",
                ids,
            ):
                plans[r["session_id"]].append(r["event_data"])
        return {sid: SessionActivity.build(counts[sid], plans[sid]) for sid in ids}

    async def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        await self._execute(
            "UPDATE sessions SET status = $1, updated_at = NOW() WHERE id = $2",
            status.value,
            session_id,
        )

    async def delete_session(self, session_id: str) -> None:
        """Delete the session, with the side-constraints and corrections it recorded."""
        pool = await self._pool()
        async with pool.acquire() as conn, conn.transaction():
            for table in ("session_constraints", "correction_records"):
                await conn.execute(f"DELETE FROM {table} WHERE session_id = $1", session_id)
            await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)

    async def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
        rows = await self._fetch(
            """SELECT id AS session_id, title AS summary,
                      ts_rank(search_vector, plainto_tsquery('english', $1)) AS score
               FROM sessions
               WHERE search_vector @@ plainto_tsquery('english', $1)
               ORDER BY score DESC
               LIMIT $2""",
            query[:500],
            limit,
        )
        return [
            {
                "session_id": r["session_id"],
                "event_type": "session",
                "summary": r.get("summary") or "",
                "score": float(r["score"] or 0.0),
            }
            for r in rows
        ]
