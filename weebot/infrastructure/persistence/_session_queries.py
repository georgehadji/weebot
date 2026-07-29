"""Session CRUD queries — extracted from SQLiteStateRepository for modularity."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)


class SessionQueries:
    """Encapsulates all session table CRUD operations.

    Shares a connection pool with the parent repository.
    """

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(self, session: Session) -> None:
        """Upsert a session row."""
        events_data = [e.model_dump() for e in session.events]
        from weebot.config.constants import MAX_EVENTS_JSON_BYTES
        events_json = json.dumps(events_data, default=str)
        while len(events_json) > MAX_EVENTS_JSON_BYTES and len(events_data) > 1:
            logger.warning(
                "Session %s events_json is %d bytes — truncating oldest events",
                session.id, len(events_json),
            )
            events_data = events_data[1:]
            events_json = json.dumps(events_data, default=str)

        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO sessions
                    (id, user_id, agent_id, status, title, events_json, context_json, created_at, updated_at)
                VALUES
                    (:id, :user_id, :agent_id, :status, :title, :events_json, :context_json, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    title = excluded.title,
                    events_json = excluded.events_json,
                    context_json = excluded.context_json,
                    updated_at = excluded.updated_at
                """,
                {
                    "id": session.id,
                    "user_id": session.user_id,
                    "agent_id": session.agent_id,
                    "status": session.status.value,
                    "title": session.title,
                    "events_json": events_json,
                    "context_json": json.dumps(session.context.model_dump(mode="json")),
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                },
            )

    async def load(self, session_id: str) -> Optional[dict[str, Any]]:
        """Load a session row by ID.
        
        Returns a dict-like row (aiosqlite.Row supports dict access)."""
        return await self._pool.execute_read(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
            fetch_all=False,
        )

    async def list(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List session rows with optional filters."""
        conditions: list[str] = []
        params: list[str] = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        return await self._pool.execute_read(
            f"SELECT * FROM sessions{where_clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (*params, str(limit), str(offset)),
        )

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        """Update just the status of a session."""
        from datetime import datetime, timezone
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.now(timezone.utc).isoformat(), session_id),
            )

    async def delete(self, session_id: str) -> None:
        """Delete a session row."""
        async with self._pool.acquire_write() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    async def count(self, user_id: Optional[str] = None) -> int:
        """Count session rows, optionally filtered by user."""
        if user_id:
            row = await self._pool.execute_read(
                "SELECT COUNT(*) as count FROM sessions WHERE user_id = ?",
                (user_id,),
                fetch_all=False,
            )
        else:
            row = await self._pool.execute_read(
                "SELECT COUNT(*) as count FROM sessions",
                fetch_all=False,
            )
        return row["count"] if row else 0
