"""Model selection strategies — strategy pattern for routing to optimal LLM.

Extracted from ``model_selection.py`` during WP-2 god module decomposition.
Each strategy implements a different selection policy:
- CostOptimized: prefers task-matched models with lowest cost
- QualityOptimized: prefers PREMIUM tier with large context windows
- Fastest: prefers FAST tier models
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.application.services.model_registry._models import ModelConfig, ModelTier
from weebot.domain.models.task_type import TaskType


def within_budget(
    candidates: list[tuple[str, ModelConfig]], budget: float | None
) -> list[tuple[str, ModelConfig]]:
    """Candidates whose cost is a real, affordable rate.

    The lower bound is not redundant with ``ModelConfig.__post_init__``: a
    dataclass is mutable, so construction-time validation does not cover an
    instance whose cost was changed afterwards. Written once rather than three
    times because a filter that decides what may be spent is the wrong thing to
    keep three copies of.
    """
    if budget is None:
        return candidates
    return [(mid, cfg) for mid, cfg in candidates if 0 <= cfg.cost_per_1k_tokens <= budget]


def effective_cost(cfg: ModelConfig) -> float:
    """Cost as a scoring term, floored at zero.

    Every strategy *subtracts* cost from a score, so a negative value would add
    score without bound and win selection regardless of task or tier.
    """
    return max(0.0, cfg.cost_per_1k_tokens)


class ModelSelectionStrategy(ABC):
    @abstractmethod
    def select(
        self,
        candidates: list[tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: float | None = None,
    ) -> str:
        """Return the selected model_id from the list of candidates."""
        ...


class CostOptimized(ModelSelectionStrategy):
    def select(
        self,
        candidates: list[tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: float | None = None,
    ) -> str:
        candidates = within_budget(candidates, budget)
        if not candidates:
            raise ValueError("No models match the budget constraint")

        # Prefer models that have the task in strengths, then lowest cost
        scored = []
        for mid, cfg in candidates:
            score = 0
            if task_type in cfg.strengths:
                score += 1000
            score -= effective_cost(cfg) * 100
            scored.append((mid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]


class QualityOptimized(ModelSelectionStrategy):
    def select(
        self,
        candidates: list[tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: float | None = None,
    ) -> str:
        candidates = within_budget(candidates, budget)
        if not candidates:
            raise ValueError("No models match the budget constraint")

        scored = []
        for mid, cfg in candidates:
            score = 0
            if task_type in cfg.strengths:
                score += 100
            if cfg.tier == ModelTier.PREMIUM:
                score += 50
            elif cfg.tier == ModelTier.STANDARD:
                score += 25
            score += cfg.context_window / 10000
            scored.append((mid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]


class Fastest(ModelSelectionStrategy):
    def select(
        self,
        candidates: list[tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: float | None = None,
    ) -> str:
        candidates = within_budget(candidates, budget)
        if not candidates:
            raise ValueError("No models match the budget constraint")

        scored = []
        for mid, cfg in candidates:
            score = 0
            if task_type in cfg.strengths:
                score += 100
            if cfg.tier == ModelTier.FAST:
                score += 50
            elif cfg.tier == ModelTier.STANDARD:
                score += 25
            score -= effective_cost(cfg) * 10
            scored.append((mid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]
