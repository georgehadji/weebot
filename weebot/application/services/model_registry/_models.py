"""Model registry — data types for LLM model configuration.

Extracted from ``model_selection.py`` during WP-2 god module decomposition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
    strengths: list[TaskType]
    tier: ModelTier
    api_key_env: str
    tool_use_score: int = 5

    def __post_init__(self) -> None:
        """Reject the two field values that silently corrupt model selection.

        A negative ``cost_per_1k_tokens`` does not merely misprice a model, it
        inverts every comparison that uses it: ``_strategies.py`` *subtracts*
        cost from score, so a negative one adds score without bound, and the
        budget filter ``cost <= budget`` admits it at any budget including zero.
        A catalog carrying four such entries made every cost- and speed-based
        selection return the same meta-router regardless of task or budget.

        Validating here rather than in the catalog generator is deliberate: the
        generator is one of several places model definitions are written, and
        this dataclass is the one seam all of them pass through.
        """
        if self.cost_per_1k_tokens < 0:
            raise ValueError(
                f"{self.name}: cost_per_1k_tokens must not be negative "
                f"(got {self.cost_per_1k_tokens!r}); a negative cost inverts every "
                f"comparison in model selection."
            )
        if not isinstance(self.context_window, int) or self.context_window <= 0:
            raise ValueError(
                f"{self.name}: context_window must be a positive int "
                f"(got {self.context_window!r})."
            )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * self.cost_per_1k_tokens / 1000
