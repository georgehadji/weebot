"""AdversarialPool — accumulates artifacts where evaluator and ground truth disagree.

When an evaluator is replaced at an epoch boundary (R3), the displaced
evaluator may have been over-lenient: accepting artifacts that the ground-truth
anchor dataset rejects.  These artifacts form an "adversarial pool" that biases
the next epoch's evaluator toward stricter, more accurate scoring.

The pool is used to inject an adversarial objective into the optimizer's prompt
for the evaluator slot.  The new evaluator is rewarded for correctly rejecting
artifacts that the old evaluator accepted but ground truth rejected.

This follows RQGM §5.4: after each evaluator replacement, the subsequent epoch
adds an adversarial regularization term to correct for evaluator drift.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AdversarialPool:
    """Accumulates adversarial artifacts from displaced evaluators.

    Usage::

        pool = AdversarialPool()
        pool.on_evaluator_replaced(old_id, new_id, artifacts)
        # Next epoch:
        objective = pool.build_adversarial_objective(epoch)
        # The objective is injected into the optimizer's evaluator prompt
    """

    def __init__(self) -> None:
        # Mapping: epoch -> list of adversarial artifact dicts
        self._pools: dict[int, list[dict]] = {}

        # Tracking: which evaluators had adversarial artifacts
        self._evaluator_artifacts: dict[str, list[dict]] = {}

        # Statistics
        self._total_artifacts: int = 0
        self._replacements_with_adversarial: int = 0

    def add_artifacts(
        self,
        evaluator_id: str,
        epoch: int,
        artifacts: list[dict],
    ) -> None:
        """Add adversarial artifacts produced by *evaluator_id* at *epoch*.

        Artifacts should be dicts with at least ``task_id``, ``description``,
        and ``accepted_by_evaluator: bool``.
        """
        if not artifacts:
            return

        if epoch not in self._pools:
            self._pools[epoch] = []
        self._pools[epoch].extend(artifacts)

        if evaluator_id not in self._evaluator_artifacts:
            self._evaluator_artifacts[evaluator_id] = []
        self._evaluator_artifacts[evaluator_id].extend(artifacts)

        self._total_artifacts += len(artifacts)
        logger.info(
            "AdversarialPool: %d artifacts from %s (epoch %d, total=%d)",
            len(artifacts), evaluator_id, epoch, self._total_artifacts,
        )

    def get_artifacts_for_epoch(self, epoch: int) -> list[dict]:
        """Return all adversarial artifacts from epochs before *epoch*.

        This is the cumulative adversarial pool available for the optimizer
        to use when designing the next evaluator prompt.
        """
        result = []
        for e, artifacts in self._pools.items():
            if e < epoch:
                result.extend(artifacts)
        return result

    def build_adversarial_objective(self, epoch: int, max_samples: int = 20) -> str:
        """Build an adversarial regularization objective string for *epoch*.

        Returns a text block that can be injected into the optimizer's prompt
        for the evaluator slot.  Describes artifacts that the previous evaluator
        scored incorrectly, asking the new evaluator to be more discriminating.
        """
        artifacts = self.get_artifacts_for_epoch(epoch)
        if not artifacts:
            return ""

        # Sample to keep prompt size manageable
        if len(artifacts) > max_samples:
            import random
            artifacts = random.sample(artifacts, max_samples)

        lines = [
            "### Adversarial Regularization Objective",
            "",
            f"The previous evaluator scored {len(artifacts)} artifacts incorrectly. "
            "These artifacts were accepted by the old evaluator but rejected by "
            "ground truth.  The new evaluator should be stricter with similar cases.",
            "",
            "Examples of incorrectly-scored artifacts:",
        ]
        for i, art in enumerate(artifacts[:10], 1):
            desc = art.get("description", art.get("task_id", f"artifact {i}"))
            eval_score = art.get("evaluator_score", "N/A")
            lines.append(f"{i}. {desc} (old score: {eval_score})")

        lines.extend([
            "",
            "Adversarial objective: The new evaluator should correctly reject "
            "artifacts like these.  If the old evaluator was over-lenient, "
            "tighten the scoring criteria.",
        ])

        return "\n".join(lines)

    def on_evaluator_replaced(
        self,
        old_evaluator_id: str,
        new_evaluator_id: str,
        epoch: int,
        artifacts: list[dict] | None = None,
    ) -> None:
        """Called when an evaluator is replaced.

        If *artifacts* are provided, they are artifacts where the old evaluator
        disagreed with ground truth.  These become the adversarial pool for
        the next epoch.
        """
        if artifacts:
            self.add_artifacts(old_evaluator_id, epoch, artifacts)
            self._replacements_with_adversarial += 1

    def stats(self) -> dict[str, Any]:
        """Return pool statistics for monitoring."""
        return {
            "total_artifacts": self._total_artifacts,
            "pools_by_epoch": {str(k): len(v) for k, v in self._pools.items()},
            "replacements_with_adversarial": self._replacements_with_adversarial,
            "evaluators_with_artifacts": len(self._evaluator_artifacts),
        }
