"""Correction records repo — extracted from SQLiteStateRepository.

Backs CorrectionTracker (ICM edit-source principle): persists each
output-correction delta and answers "how many times has this category
recurred" so recurring patterns can be surfaced as source-level fixes.
"""
from __future__ import annotations

from weebot.domain.models.correction import CorrectionRecord
from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool


class CorrectionRecordRepo:
    """Manages the correction_records table."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(self, record: CorrectionRecord) -> None:
        """Insert a correction record."""
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO correction_records
                    (id, session_id, step_id, step_description, original_output,
                     corrected_output, correction_category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{record.session_id}:{record.step_id}:{record.created_at.isoformat()}",
                    record.session_id,
                    record.step_id,
                    record.step_description,
                    record.original_output,
                    record.corrected_output,
                    record.correction_category,
                    record.created_at.isoformat(),
                ),
            )

    async def count_by_category(self, category: str) -> int:
        """Count all correction records in a category."""
        row = await self._pool.execute_read(
            "SELECT COUNT(*) AS n FROM correction_records WHERE correction_category = ?",
            (category,),
            fetch_all=False,
        )
        return int(row["n"]) if row else 0

    async def get_patterns(self, min_count: int = 3) -> list[dict]:
        """Return categories whose record count meets or exceeds min_count."""
        rows = await self._pool.execute_read(
            """
            SELECT correction_category AS category, COUNT(*) AS count
            FROM correction_records
            GROUP BY correction_category
            HAVING COUNT(*) >= ?
            ORDER BY count DESC
            """,
            (min_count,),
        )
        return [dict(r) for r in rows]
