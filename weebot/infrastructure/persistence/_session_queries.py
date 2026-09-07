"""Session CRUD queries — extracted from SQLiteStateRepository for modularity."""

from __future__ import annotations

import json
import logging
from typing import Any

from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool
from datetime import UTC

logger = logging.getLogger(__name__)


class SessionQueries:
    """Encapsulates all session table CRUD operations.

    Shares a connection pool with the parent repository.
    """

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(self, session: Session) -> int:
        """Upsert a session row. Returns how many oldest events were dropped.

        The ``MAX_EVENTS_JSON_BYTES`` ceiling is enforced HERE and only here.
        ``SQLiteStateRepository.save_session`` used to run a byte-for-byte
        identical loop of its own immediately before calling this one, and then
        throw the result away — it passes the ``Session``, not the trimmed list,
        so this loop always re-did the work from the original events. One rule,
        two implementations, and the copy that ran first was the one nothing
        read.

        Returning the count is what lets the caller act on the outcome instead
        of recomputing it.
        """
        events_data = [e.model_dump() for e in session.events]
        from weebot.config.constants import MAX_EVENTS_JSON_BYTES

        events_json = json.dumps(events_data, default=str)
        original_count = len(events_data)
        original_bytes = len(events_json)
        while len(events_json) > MAX_EVENTS_JSON_BYTES and len(events_data) > 1:
            events_data = events_data[1:]
            events_json = json.dumps(events_data, default=str)
        dropped = original_count - len(events_data)
        if dropped:
            # One line for the whole truncation, not one per dropped event.
            # With the duplicate loop in place this logged 2N lines for N
            # dropped events, from two different module names, which read like
            # two separate faults.
            logger.warning(
                "Session %s events_json was %d bytes over the %d-byte ceiling — "
                "dropped the %d oldest of %d events to fit the row",
                session.id,
                original_bytes,
                MAX_EVENTS_JSON_BYTES,
                dropped,
                original_count,
            )

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
        return dropped

    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Load a session row by ID.

        Returns a dict (converted from aiosqlite.Row for type safety)."""
        row = await self._pool.execute_read(
            "SELECT * FROM sessions WHERE id = ?", (session_id,), fetch_all=False
        )
        return dict(row) if row is not None else None

    async def list(
        self,
        user_id: str | None = None,
        status: str | None = None,
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
        rows = await self._pool.execute_read(
            f"SELECT * FROM sessions{where_clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (*params, str(limit), str(offset)),
        )
        return [dict(r) for r in rows]

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        """Update just the status of a session."""
        from datetime import datetime

        async with self._pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.now(UTC).isoformat(), session_id),
            )

    async def delete(self, session_id: str) -> None:
        """Delete a session row."""
        async with self._pool.acquire_write() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    async def count(self, user_id: str | None = None) -> int:
        """Count session rows, optionally filtered by user."""
        if user_id:
            row = await self._pool.execute_read(
                "SELECT COUNT(*) as count FROM sessions WHERE user_id = ?",
                (user_id,),
                fetch_all=False,
            )
        else:
            row = await self._pool.execute_read(
                "SELECT COUNT(*) as count FROM sessions", fetch_all=False
            )
        return row["count"] if row else 0
