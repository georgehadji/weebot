"""Commitment CRUD — extracted from SQLiteStateRepository for modularity."""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)


class CommitmentRepo:
    """Manages the commitments table."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(
        self,
        commitment_id: str,
        promise_text: str,
        context: str,
        source_session_id: str,
        source_event_id: str | None = None,
        due_at: str | None = None,
        status: str = "pending",
    ) -> None:
        """Insert or update a commitment."""
        now = datetime.now(UTC).isoformat()
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO commitments
                    (id, promise_text, context, source_session_id, source_event_id,
                     due_at, status, created_at, updated_at)
                VALUES
                    (:id, :promise_text, :context, :source_session_id, :source_event_id,
                     :due_at, :status, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    context = excluded.context,
                    updated_at = excluded.updated_at
                """,
                {
                    "id": commitment_id,
                    "promise_text": promise_text,
                    "context": context,
                    "source_session_id": source_session_id,
                    "source_event_id": source_event_id or "",
                    "due_at": due_at or "",
                    "status": status,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    async def list(self, status: str | None = None) -> list[dict]:
        """List commitments, optionally filtered by status."""
        if status:
            rows = await self._pool.execute_read(
                "SELECT * FROM commitments WHERE status = ? ORDER BY created_at DESC", (status,)
            )
        else:
            rows = await self._pool.execute_read(
                "SELECT * FROM commitments ORDER BY created_at DESC"
            )
        return [dict(r) for r in rows]

    async def get_pending(self) -> list[dict]:
        """Get all pending commitments."""
        rows = await self._pool.execute_read(
            "SELECT * FROM commitments WHERE status = 'pending' ORDER BY created_at ASC"
        )
        return [dict(r) for r in rows]

    async def update_status(
        self, commitment_id: str, status: str, failure_reason: str | None = None
    ) -> None:
        """Update a commitment's status."""
        now = datetime.now(UTC).isoformat()
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                UPDATE commitments
                SET status = ?, updated_at = ?, failure_reason = ?
                WHERE id = ?
                """,
                (status, now, failure_reason or "", commitment_id),
            )
