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
    #: True when no evaluation happened -- the evaluator raised, or returned
    #: nothing usable -- and `score`/`passed` are the fail-open default rather
    #: than a verdict. Without this a caller cannot tell a step judged perfect
    #: from a step never judged at all, because both arrive as score=1.0,
    #: passed=True. Defaults False, so every honest verdict is unaffected.
    evaluator_failed: bool = False


class StepEvaluatorPort(ABC):
    """Abstract port for evaluating step output against plan goals.

    Implementations:
    - NoOpStepEvaluator — always passes (backward-compatible default)
    - LLMStepEvaluator — calls cheap model to score step output
    """

    @abstractmethod
    async def evaluate(
        self, step: Step, output: str, plan: Plan, previous_outputs: list[str]
    ) -> StepEvaluation: ...
