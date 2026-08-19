"""Session constraints repo — persists SessionConstraintRegistry entries.

Backs the Lost-in-Compaction side-constraint registry: a user-issued
directive persisted per-session so it survives compaction and reconnects
independently of the (evictable, compactable) executor conversation buffer.
See tasks/specs/side_constraint_integrity_plan.md.
"""
from __future__ import annotations

from weebot.domain.models.session_constraint import SessionConstraint
from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool


class SessionConstraintRepo:
    """Manages the session_constraints table."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(self, session_id: str, constraint: SessionConstraint) -> None:
        """Insert a session constraint."""
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO session_constraints
                    (id, session_id, text, evidence_span, kind, direction,
                     turn_index, revoked_at, superseded_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{session_id}:{constraint.turn_index}:{constraint.created_at.isoformat()}",
                    session_id,
                    constraint.text,
                    constraint.evidence_span,
                    constraint.kind.value,
                    constraint.direction.value,
                    constraint.turn_index,
                    constraint.revoked_at.isoformat() if constraint.revoked_at else None,
                    constraint.superseded_by,
                    constraint.created_at.isoformat(),
                ),
            )

    async def revoke(self, session_id: str, text: str, revoked_at) -> None:
        """Mark every active constraint matching *text* in *session_id* revoked."""
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                UPDATE session_constraints
                SET revoked_at = ?
                WHERE session_id = ? AND text = ? AND revoked_at IS NULL
                    AND superseded_by IS NULL
                """,
                (revoked_at.isoformat(), session_id, text),
            )

    async def list_active(self, session_id: str) -> list[dict]:
        """Return active (non-revoked, non-superseded) constraints for a session."""
        rows = await self._pool.execute_read(
            """
            SELECT text, evidence_span, kind, direction, turn_index, created_at
            FROM session_constraints
            WHERE session_id = ? AND revoked_at IS NULL AND superseded_by IS NULL
            ORDER BY turn_index ASC
            """,
            (session_id,),
        )
        return [dict(r) for r in rows]
