"""Memory metadata repository — salience scoring and eviction."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)


class MemoryMetadataRepo:
    """Manages the memory_metadata table for salience-scored entries."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def upsert(
        self,
        entry_hash: str,
        entry_text: str,
        source: str = "agent",
        salience: Optional[float] = None,
    ) -> None:
        """Insert or update a memory metadata entry with salience scoring.

        With ``salience=None`` (the default), an access-count bump path is used:
        insert at 0.5, or +0.05 per subsequent access capped at 1.0. Passing an
        explicit ``salience`` pins the row at that value — it can only raise the
        existing score on conflict, never lower it (a pinned high-value entry,
        e.g. the consolidated user profile, must not decay from routine reads).
        """
        now = datetime.now(timezone.utc).isoformat()
        insert_salience = 0.5 if salience is None else salience
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO memory_metadata
                    (entry_hash, entry_text, source, salience, access_count, last_accessed, created_at)
                VALUES
                    (:hash, :text, :source, :insert_salience, 1, :now, :now)
                ON CONFLICT(entry_hash) DO UPDATE SET
                    entry_text = :text,
                    source = :source,
                    access_count = access_count + 1,
                    salience = CASE
                        WHEN :salience IS NOT NULL THEN MAX(salience, :salience)
                        ELSE MIN(1.0, salience + 0.05)
                    END,
                    last_accessed = :now
                """,
                {
                    "hash": entry_hash,
                    "text": entry_text,
                    "source": source,
                    "insert_salience": insert_salience,
                    "salience": salience,
                    "now": now,
                },
            )

    async def get_by_hash(self, entry_hash: str) -> Optional[dict]:
        """Return a single memory metadata entry by hash, or None if absent."""
        rows = await self._pool.execute_read(
            """
            SELECT entry_hash, entry_text, source, salience, access_count,
                   last_accessed, created_at
            FROM memory_metadata
            WHERE entry_hash = ?
            """,
            (entry_hash,),
        )
        return dict(rows[0]) if rows else None

    async def get_low_salience(
        self, threshold: float = 0.3, limit: int = 50
    ) -> list[dict]:
        """Get memory entries below the salience threshold (eviction candidates)."""
        rows = await self._pool.execute_read(
            """
            SELECT entry_hash, entry_text, source, salience, access_count,
                   last_accessed, created_at
            FROM memory_metadata
            WHERE salience < ?
            ORDER BY salience ASC
            LIMIT ?
            """,
            (threshold, limit),
        )
        return [dict(r) for r in rows]

    async def delete_entries(self, entry_hashes: list[str]) -> int:
        """Delete specific memory entries by hash. Returns count deleted."""
        if not entry_hashes:
            return 0
        placeholders = ",".join("?" for _ in entry_hashes)
        async with self._pool.acquire_write() as conn:
            cursor = await conn.execute(
                f"DELETE FROM memory_metadata WHERE entry_hash IN ({placeholders})",
                entry_hashes,
            )
            return cursor.rowcount if hasattr(cursor, "rowcount") else 0

    async def get_all(self, limit: int = 200) -> list[dict]:
        """Return all memory metadata entries (for bulk operations)."""
        rows = await self._pool.execute_read(
            "SELECT * FROM memory_metadata ORDER BY salience DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
