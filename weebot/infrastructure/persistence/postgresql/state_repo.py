"""PostgreSQL state repository — implements StateRepositoryPort via asyncpg.

Requires ``WEEBOT_DB_BACKEND=postgresql`` environment variable to activate.
SQLite remains the default.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.postgresql.connection import get_pool


class PostgreSQLStateRepository(StateRepositoryPort):
    """PostgreSQL-backed session persistence.

    Uses per-domain connection pools (sessions domain).
    """

    async def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        pool = await get_pool("sessions")
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    title TEXT,
                    context JSONB NOT NULL DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS session_events (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    idx INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_session_events_session
                    ON session_events(session_id, idx);
                -- Full-text search support
                ALTER TABLE sessions ADD COLUMN IF NOT EXISTS search_vector tsvector;
            """)

    async def save_session(self, session: Session) -> None:
        pool = await get_pool("sessions")
        async with pool.acquire() as conn:
            # Upsert session record
            await conn.execute(
                """INSERT INTO sessions (id, user_id, agent_id, status, title, context, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                   ON CONFLICT (id) DO UPDATE SET
                       status = EXCLUDED.status,
                       title = EXCLUDED.title,
                       context = EXCLUDED.context,
                       updated_at = EXCLUDED.updated_at""",
                session.id,
                session.user_id,
                session.agent_id,
                session.status.value,
                session.title,
                session.context.model_dump_json(),
                session.created_at,
                session.updated_at,
            )
            # Delete and re-insert events (idempotent)
            await conn.execute(
                "DELETE FROM session_events WHERE session_id = $1", session.id
            )
            for idx, event in enumerate(session.events):
                await conn.execute(
                    """INSERT INTO session_events (session_id, idx, event_type, event_data)
                       VALUES ($1, $2, $3, $4::jsonb)""",
                    session.id, idx, type(event).__name__,
                    event.model_dump_json(),
                )

    async def load_session(self, session_id: str) -> Optional[Session]:
        pool = await get_pool("sessions")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sessions WHERE id = $1", session_id
            )
            if row is None:
                return None
            # Load events
            event_rows = await conn.fetch(
                "SELECT event_data FROM session_events WHERE session_id = $1 ORDER BY idx",
                session_id,
            )
            events = []
            for er in event_rows:
                try:
                    events.append(json.loads(er["event_data"]))
                except (json.JSONDecodeError, TypeError):
                    pass
            data = dict(row)
            data["events"] = events
            if data.get("context") and isinstance(data["context"], str):
                data["context"] = json.loads(data["context"])
            return Session.model_validate(data)

    async def list_sessions(self, user_id: Optional[str] = None) -> list:
        pool = await get_pool("sessions")
        async with pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch(
                    "SELECT * FROM sessions WHERE user_id = $1 ORDER BY updated_at DESC",
                    user_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM sessions ORDER BY updated_at DESC"
                )
            return [Session.model_validate(dict(r)) for r in rows]

    async def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        pool = await get_pool("sessions")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET status = $1, updated_at = NOW() WHERE id = $2",
                status.value, session_id,
            )

    async def delete_session(self, session_id: str) -> None:
        pool = await get_pool("sessions")
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)

    async def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
        pool = await get_pool("sessions")
        async with pool.acquire() as conn:
            # Use PostgreSQL full-text search
            rows = await conn.fetch(
                """SELECT id AS session_id, status,
                          title AS summary,
                          ts_rank(search_vector, plainto_tsquery('english', $1)) AS score
                   FROM sessions
                   WHERE search_vector @@ plainto_tsquery('english', $1)
                   ORDER BY score DESC
                   LIMIT $2""",
                query, limit,
            )
            return [
                {
                    "session_id": r["session_id"],
                    "event_type": "session",
                    "summary": r.get("summary", "") or "",
                    "score": float(r["score"]) if r["score"] else 0.0,
                }
                for r in rows
            ]
