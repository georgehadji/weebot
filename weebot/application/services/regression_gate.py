"""RegressionGate — validates harness candidates against held-in and held-out splits.

Implements the paper's acceptance rule:
  Δ_in ≥ 0 AND Δ_ho ≥ 0 AND max(Δ_in, Δ_ho) > 0

Phase 4 will implement the actual benchmark-driven validation.  For now
this is a stub that accepts every proposal (always-approve gate) so that
the HarnessOptFlow can be tested end-to-end.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from weebot.domain.models.harness_edit import PromotionDecision

logger = logging.getLogger(__name__)


class RegressionGate:
    """Validates harness candidates through progressive regression testing.

    Phase 4 implementation will:
      1. Run held-in tasks under both harnesses → Δ_in
      2. If Δ_in < 0 → REJECT
      3. Run held-out tasks under both harnesses → Δ_ho
      4. If Δ_ho < 0 → REJECT
      5. If max(Δ_in, Δ_ho) ≤ 0 → REJECT
      6. ACCEPT

    For now (Phase 3), this is a stub that always accepts, enabling
    end-to-end testing of the HarnessOptFlow loop.
    """

    def __init__(
        self,
        flow_factory: Optional[Callable] = None,
    ):
        self._flow_factory = flow_factory

    async def validate(
        self,
        baseline: Any,
        candidate: Any,
        held_in_tasks: Optional[list[str]] = None,
        held_out_tasks: Optional[list[str]] = None,
        repeats: int = 2,
    ) -> PromotionDecision:
        """Validate a candidate harness against a baseline.

        Args:
            baseline: Current (baseline) harness config.
            candidate: Proposed candidate harness config.
            held_in_tasks: Task IDs for measuring improvement.
            held_out_tasks: Task IDs for regression detection.
            repeats: Number of repeated runs (for stochastic stability).

        Returns:
            ``PromotionDecision`` with ``accepted=True`` (stub).
        """
        logger.info(
            "RegressionGate stub: auto-accepting candidate %s",
            getattr(candidate, "version", "unknown"),
        )
        return PromotionDecision(
            accepted=True,
            delta_in=0.05,  # Stub: pretend 5% held-in improvement
            delta_ho=0.02,  # Stub: pretend 2% held-out improvement
            reason="Stub gate: auto-accepted (Phase 4 will implement real validation)",
        )
