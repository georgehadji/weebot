"""Port for evaluating step progress against plan goals."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.domain.models.plan import Plan, Step


@dataclass(frozen=True)
class StepEvaluation:
    step_id: str
    score: float  # 0.0–1.0
    passed: bool
    regression_detected: bool
    reasoning: str
    recommendations: list[str] = field(default_factory=list)


class StepEvaluatorPort(ABC):
    """Abstract port for evaluating step output against plan goals.

    Implementations:
    - NoOpStepEvaluator — always passes (backward-compatible default)
    - LLMStepEvaluator — calls cheap model to score step output
    """

    @abstractmethod
    async def evaluate(
        self,
        step: "Step",
        output: str,
        plan: "Plan",
        previous_outputs: list[str],
    ) -> StepEvaluation: ...
