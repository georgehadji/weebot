"""Model selection strategies — strategy pattern for routing to optimal LLM.

Extracted from ``model_selection.py`` during WP-2 god module decomposition.
Each strategy implements a different selection policy:
- CostOptimized: prefers task-matched models with lowest cost
- QualityOptimized: prefers PREMIUM tier with large context windows
- Fastest: prefers FAST tier models
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from weebot.application.services.model_registry._models import ModelConfig, ModelTier
from weebot.domain.models.task_type import TaskType


class ModelSelectionStrategy(ABC):
    @abstractmethod
    def select(
        self,
        candidates: List[Tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: Optional[float] = None,
    ) -> str:
        """Return the selected model_id from the list of candidates."""
        ...


class CostOptimized(ModelSelectionStrategy):
    def select(
        self,
        candidates: List[Tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: Optional[float] = None,
    ) -> str:
        # Filter by budget
        if budget is not None:
            candidates = [(mid, cfg) for mid, cfg in candidates if cfg.cost_per_1k_tokens <= budget]
        if not candidates:
            raise ValueError("No models match the budget constraint")

        # Prefer models that have the task in strengths, then lowest cost
        scored = []
        for mid, cfg in candidates:
            score = 0
            if task_type in cfg.strengths:
                score += 1000
            score -= cfg.cost_per_1k_tokens * 100
            scored.append((mid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]


class QualityOptimized(ModelSelectionStrategy):
    def select(
        self,
        candidates: List[Tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: Optional[float] = None,
    ) -> str:
        if budget is not None:
            candidates = [(mid, cfg) for mid, cfg in candidates if cfg.cost_per_1k_tokens <= budget]
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
        candidates: List[Tuple[str, ModelConfig]],
        task_type: TaskType,
        budget: Optional[float] = None,
    ) -> str:
        if budget is not None:
            candidates = [(mid, cfg) for mid, cfg in candidates if cfg.cost_per_1k_tokens <= budget]
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
            score -= cfg.cost_per_1k_tokens * 10
            scored.append((mid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]
