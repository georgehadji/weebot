"""Commitment CRUD — extracted from SQLiteStateRepository for modularity."""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)

# One row per promise (audit A12). Rows saved while ids were a fresh uuid4 per save can
# repeat a natural key: keep the one whose status moved past pending, else the oldest.
# The alembic revision f2c0mm1t0001 runs the same two statements.
DEDUP_SQL = """
DELETE FROM commitments WHERE rowid NOT IN (
    SELECT rowid FROM (
        SELECT rowid, ROW_NUMBER() OVER (
            PARTITION BY source_session_id, COALESCE(source_event_id, ''), promise_text
            ORDER BY status = 'pending', created_at, rowid
        ) AS rank FROM commitments
    ) WHERE rank = 1
)
"""
UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commitments_natural_key "
    "ON commitments(source_session_id, source_event_id, promise_text)"
)


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
        """Insert a commitment; one already stored, by id or by natural key, is left as it is."""
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
                ON CONFLICT DO NOTHING
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
