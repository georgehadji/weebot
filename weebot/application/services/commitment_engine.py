"""CommitmentEngine — heartbeat and surfacing for agent commitments.

Heartbeat runs periodically (every 30 min) via APScheduler to:
- Mark commitments past their due_at as OVERDUE
- Generate follow-up suggestions for the next interactive session

Surfacing runs on session start to:
- Inject pending/overdue commitments into session context
- Allow the agent to proactively address outstanding promises
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from weebot.domain.models.commitment import Commitment, CommitmentStatus

logger = logging.getLogger(__name__)


class CommitmentEngine:
    """Manages the commitment lifecycle: extraction → tracking → surfacing.

    Relies on an external persistence layer (``state_repo``) that implements
    the commitment CRUD interface (``save_commitment``, ``get_pending_commitments``,
    ``update_commitment_status``, ``list_commitments``).

    Args:
        state_repo: A repository object with commitment CRUD methods.
            Typically ``SQLiteStateRepository`` or a test mock.
    """

    def __init__(self, state_repo) -> None:
        self._repo = state_repo

    # ── Heartbeat ───────────────────────────────────────────────────

    async def heartbeat(self) -> dict:
        """Run a heartbeat cycle: scan for overdue commitments.

        Returns:
            Dict with stats: ``checked``, ``marked_overdue``, ``active_pending``.
        """
        stats: dict = {"checked": 0, "marked_overdue": 0, "active_pending": 0}

        try:
            pending = await self._repo.list_commitments(status="pending", limit=200)
        except Exception as exc:
            logger.warning("CommitmentEngine heartbeat: failed to list commitments: %s", exc)
            return stats

        now = datetime.now(timezone.utc)
        for cmt in pending:
            stats["checked"] += 1
            if cmt.due_at and cmt.due_at < now:
                try:
                    await self._repo.update_commitment_status(
                        cmt.id, "overdue",
                        failure_reason="Heartbeat: due_at passed without follow-up",
                    )
                    stats["marked_overdue"] += 1
                    logger.info(
                        "Commitment %s marked OVERDUE (due_at=%s, promise=%r)",
                        cmt.id[:8], cmt.due_at.isoformat(), cmt.promise_text[:60],
                    )
                except Exception as exc:
                    logger.warning("Failed to update commitment %s: %s", cmt.id[:8], exc)

        stats["active_pending"] = len(pending) - stats["marked_overdue"]
        return stats

    # ── Surfacing ──────────────────────────────────────────────────

    async def get_pending_summary(self, limit: int = 10) -> str:
        """Build a natural-language summary of pending/overdue commitments.

        Returns:
            A string suitable for injection into session context or
            empty string if no pending commitments exist.
        """
        try:
            pending = await self._repo.get_pending_commitments(limit=limit)
        except Exception as exc:
            logger.warning("CommitmentEngine surfacing: failed: %s", exc)
            return ""

        if not pending:
            return ""

        overdue = [c for c in pending if c.status == CommitmentStatus.OVERDUE]
        active = [c for c in pending if c.status == CommitmentStatus.PENDING]
        lines: list[str] = []

        if overdue:
            lines.append(f"You have {len(overdue)} overdue commitment(s):")
            for c in overdue:
                lines.append(f"  - \"{c.promise_text}\"")
                if c.due_at:
                    lines[-1] += f" (was due {c.due_at.strftime('%Y-%m-%d %H:%M')})"
                if c.context:
                    lines[-1] += f" — context: {c.context[:100]}"
        if active:
            lines.append(f"You have {len(active)} pending commitment(s):")
            for c in active:
                lines.append(f"  - \"{c.promise_text}\"")
                if c.due_at:
                    lines[-1] += f" (due {c.due_at.strftime('%Y-%m-%d %H:%M')})"

        if lines:
            summary = "\n".join(lines)
            logger.debug("CommitmentEngine: %d overdue, %d active", len(overdue), len(active))
            return summary

        return ""
