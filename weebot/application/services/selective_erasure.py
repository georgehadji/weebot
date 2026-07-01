"""SelectiveErasure — manages evaluator-dependent record lifecycle (RQGM §3.3).

When an evaluator is replaced at epoch boundaries, records scored by the
displaced evaluator must be selectively erased: evaluator-dependent records
(marked with the old evaluator's ID) are discarded, while evaluator-independent
records (verifier results, benchmark pass/fail) are kept.

The erasure is NOT immediate — it's lazy/amortized.  Stale records are
re-scored when later evaluations revisit the affected nodes, rather than
re-scoring the entire archive at once.  This reduces the O(B^2) cost of
re-scoring to O(B) via exponentially spaced checkpoints (Prop. 6 in RQGM).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SelectiveErasure:
    """Manages which records are erased when an evaluator is replaced.

    Usage::

        erasure = SelectiveErasure()
        erasure.on_evaluator_replaced(old_evaluator_id, new_evaluator_id, epoch)

        # When loading records, check if they're stale:
        if erasure.is_stale(record.evaluator_id):
            record = await re_score(record)

        # Get statistics:
        stats = erasure.stats()
    """

    def __init__(self) -> None:
        # Mapping: displaced evaluator_id -> (replacement evaluator_id, epoch)
        self._replacements: dict[str, tuple[str, int]] = {}

        # Tracking
        self._total_replacements: int = 0
        self._total_erased: int = 0
        self._total_lazy_rescored: int = 0

    def on_evaluator_replaced(
        self,
        old_evaluator_id: str,
        new_evaluator_id: str,
        epoch: int,
    ) -> None:
        """Register an evaluator replacement.

        Future ``is_stale()`` calls with ``old_evaluator_id`` will return True.
        """
        self._replacements[old_evaluator_id] = (new_evaluator_id, epoch)
        self._total_replacements += 1
        logger.info(
            "SelectiveErasure: evaluator %s replaced by %s (epoch %d)",
            old_evaluator_id, new_evaluator_id, epoch,
        )

    def is_stale(self, evaluator_id: str) -> bool:
        """Return True if *evaluator_id* has been displaced by a replacement.

        Records scored by a displaced evaluator should be re-scored before
        being used for selection.
        """
        return evaluator_id in self._replacements

    @property
    def current_replacement(self) -> tuple[str, str, int] | None:
        """Return the most recent replacement, or None."""
        if not self._replacements:
            return None
        last_id = list(self._replacements.keys())[-1]
        new_id, epoch = self._replacements[last_id]
        return (last_id, new_id, epoch)

    def mark_rescored(self, count: int = 1) -> None:
        """Increment the count of lazily re-scored records."""
        self._total_lazy_rescored += count

    def mark_erased(self, count: int = 1) -> None:
        """Increment the count of erased records."""
        self._total_erased += count

    def stats(self) -> dict[str, Any]:
        """Return erasure statistics for logging and monitoring."""
        return {
            "total_replacements": self._total_replacements,
            "total_erased": self._total_erased,
            "total_lazy_rescored": self._total_lazy_rescored,
            "active_displaced_evaluators": len(self._replacements),
        }
