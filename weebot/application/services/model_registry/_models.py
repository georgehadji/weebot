"""Model registry — data types for LLM model configuration.

Extracted from ``model_selection.py`` during WP-2 god module decomposition.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

from weebot.domain.models.task_type import TaskType


class ModelTier(Enum):
    PREMIUM = "premium"
    STANDARD = "standard"
    FAST = "fast"
    LOCAL = "local"


@dataclass
class ModelConfig:
    name: str
    provider: str
    cost_per_1k_tokens: float
    context_window: int
    strengths: List[TaskType]
    tier: ModelTier
    api_key_env: str

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * self.cost_per_1k_tokens / 1000
