"""EvaluatorState — domain model for co-evolvable evaluators (RQGM §3).

An evaluator is a first-class object that the optimizer can edit alongside
task agent skills.  At epoch boundaries, the incumbent evaluator is compared
against challengers on a ground-truth anchor dataset.  If a challenger
statistically outperforms, it replaces the incumbent via selective erasure.

Architecture note: This is a **domain model** — it has no dependencies on
infrastructure or application services.  It models the concept of an
evaluator that can be evolved, replaced, and tracked across epochs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class EvaluatorReplacement(BaseModel):
    """Record of one evaluator replacement event.

    Logged each time an evaluator is replaced at an epoch boundary.
    """

    replaced_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    epoch: int = Field(description="Epoch at which replacement occurred")
    old_evaluator_id: str = Field(description="Evaluator that was replaced")
    new_evaluator_id: str = Field(description="Evaluator that replaced it")
    old_anchor_accuracy: float = Field(ge=0.0, le=1.0, description="Incumbent's accuracy on anchor")
    new_anchor_accuracy: float = Field(ge=0.0, le=1.0, description="Challenger's accuracy on anchor")
    reason: str = Field(default="", description="Why the replacement was triggered")


class EvaluatorState(BaseModel):
    """An evaluator that can be co-evolved with task agents.

    The optimizer can propose edits to the evaluator's prompt just as it
    proposes edits to a skill document.  At epoch boundaries, the challenger
    evaluator (if any) is compared against the incumbent on a ground-truth
    anchor dataset.  If the challenger statistically outperforms (via
    epsilon-best-belief score), it replaces the incumbent.
    """

    evaluator_id: str = Field(description="Unique evaluator identifier")
    evaluator_type: str = Field(
        description="Type: judge, scorer, or reviewer",
    )
    prompt: str = Field(
        description="The evaluator's scoring/rubric prompt (mutable via optimizer)",
    )
    anchor_accuracy: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Accuracy on ground-truth anchor dataset",
    )
    anchor_total: int = Field(
        default=0, ge=0,
        description="Number of anchor tasks evaluated",
    )
    replacement_history: list[EvaluatorReplacement] = Field(
        default_factory=list,
        description="Lineage of evaluator replacements leading to this state",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def best_belief(self) -> float:
        """Epsilon-best-belief score — a conservative lower bound on accuracy.

        Uses the inverse regularized incomplete Beta function to compute
        the epsilon-quantile of the posterior over the evaluator's accuracy.
        Higher values = more confidence that this evaluator will score well.

        This is the same metric used for agent selection in RQGM §3.1.
        """
        if self.anchor_total == 0:
            return 0.0
        successes = int(self.anchor_accuracy * self.anchor_total)
        failures = self.anchor_total - successes
        # Beta(1 + S, 1 + F) posterior, epsilon = 0.05 (lower bound)
        # Simplified: use lower Wald confidence interval bound
        import math
        if successes + failures == 0:
            return 0.0
        p = successes / (successes + failures)
        z = 1.96  # 95% confidence
        se = math.sqrt(p * (1 - p) / (successes + failures))
        return max(0.0, p - z * se)

    def statistically_outperforms(self, other: "EvaluatorState", epsilon: float = 0.05) -> bool:
        """Return True if this evaluator statistically outperforms *other*.

        Uses best-belief comparison at epsilon confidence level.
        """
        return self.best_belief > other.best_belief + epsilon

    def summary(self) -> str:
        """Human-readable summary for logging and evolution tracking."""
        return (
            f"Evaluator({self.evaluator_id}, "
            f"type={self.evaluator_type}, "
            f"anchor_accuracy={self.anchor_accuracy:.3f} "
            f"({self.anchor_total} tasks), "
            f"replacements={len(self.replacement_history)})"
        )
