"""Port for evaluation judges.

A judge evaluates an agent's output against a set of criteria and returns
a per-criterion score with reasoning.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CriterionScore:
    """Score for a single evaluation criterion.

    Attributes:
        name: Criterion name (e.g. "correctness", "completeness").
        score: Score on a 0.0–10.0 scale.
        reasoning: One-sentence justification for the score.
    """
    name: str
    score: float  # 0.0–10.0
    reasoning: str = ""


@dataclass(frozen=True)
class JudgeVerdict:
    """Result of evaluating an output against criteria.

    Attributes:
        criteria: Per-criterion scores.
        overall_score: Normalized 0.0–1.0 overall score.
        passed: Whether the output meets the pass threshold.
        reasoning: Summary reasoning.
    """
    criteria: list[CriterionScore] = field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = True
    reasoning: str = ""

    @property
    def average_score(self) -> float:
        """Mean of per-criterion scores, or overall_score if no criteria."""
        if not self.criteria:
            return self.overall_score
        return sum(c.score for c in self.criteria) / len(self.criteria)


class JudgePort(ABC):
    """Abstract judge that scores an agent's output against criteria.

    Implementations:
    - ModelJudge — LLM-based (costs tokens, flexible)
    - ScoreJudge — deterministic (fast, free)
    """

    @abstractmethod
    async def judge(
        self,
        task_description: str,
        output: str,
        criteria: list[str],
        context: str = "",
    ) -> JudgeVerdict: ...
