"""HarnessMetrics — the paper's six harness-level metrics (§5.2.1) as an immutable model.

Represents the six dimensions for evaluating harness quality after a
harness edit (or a set of evaluation sessions).  A ``composite()`` helper
produces a single comparable scalar for the ``RegressionGate``.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HarnessMetrics(BaseModel):
    """Six harness-level metrics from the Code-as-Harness paper (§5.2.1).

    All fields are normalised 0.0–1.0 unless otherwise noted.

    Attributes:
        trajectory_efficiency: Tool calls / tokens / wall-clock per solved task
            (higher = more efficient).  Computed from a finished Session's event log.
        verification_strength: Gate coverage × oracle diversity (from Phase 3
            ActionEvidence).  Higher = more thorough verification before accepting
            each step.
        recovery_ability: Fraction of transient failures the agent recovered from
            without human intervention.
        state_consistency: Checkpoint/replay divergence score.  1.0 = fully
            reconstructable from logs; 0.0 = irreproducible.
        safety_compliance: Fraction of actions within the permitted capability tier
            (from Phase 4 Governance).  1.0 = every action was authorised.
        replayability: Fraction of trajectory reconstructable from persisted events.
        task_pass_rate: The existing scalar — fraction of tasks the agent solved
            in the evaluation set.
    """

    trajectory_efficiency: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Normalised efficiency score (tool calls / tokens / wall-clock)",
    )
    verification_strength: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Gate coverage × oracle diversity",
    )
    recovery_ability: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Fraction of transient failures recovered without human help",
    )
    state_consistency: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Checkpoint/replay divergence score",
    )
    safety_compliance: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Fraction of actions within permitted capability tier",
    )
    replayability: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Fraction of trajectory reconstructable from logs",
    )
    task_pass_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Fraction of evaluation tasks solved",
    )

    def composite(self, weights: Optional[dict[str, float]] = None) -> float:
        """Weighted composite score for the RegressionGate.

        Default weights reflect the paper's prioritisation: task_pass_rate
        and verification_strength are weighted highest; safety_compliance
        is a hard constraint threshold (minimum viable) rather than a
        continuous optimiser — we exclude it from the composite because it
        should never degrade (it is a gate precondition, not an optimiser).

        Args:
            weights: Per-metric weight dict (default uses the paper's
                emphasis: pass rate + verif strength get 2× weight).

        Returns:
            Weighted sum, clamped to [0.0, 1.0].
        """
        if weights is not None:
            total = sum(v for v in weights.values())
            if total <= 0:
                raise ValueError("Sum of weights must be > 0")
            score = sum(
                getattr(self, metric, 0.0) * weight
                for metric, weight in weights.items()
            ) / total
        else:
            # Default weights: pass rate + verification strength highest
            score = (
                self.task_pass_rate * 2.0
                + self.verification_strength * 2.0
                + self.trajectory_efficiency * 1.0
                + self.recovery_ability * 1.0
                + self.state_consistency * 0.5
                + self.replayability * 0.5
            ) / 7.0

        return max(0.0, min(1.0, score))

    def __str__(self) -> str:
        return (
            f"HarnessMetrics(eff={self.trajectory_efficiency:.3f}, "
            f"verif={self.verification_strength:.3f}, "
            f"recover={self.recovery_ability:.3f}, "
            f"state={self.state_consistency:.3f}, "
            f"safety={self.safety_compliance:.3f}, "
            f"replay={self.replayability:.3f}, "
            f"pass={self.task_pass_rate:.3f})"
        )
