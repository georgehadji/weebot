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
    # From OpenRouter's /api/v1/models. None means "not known" -- a hand-added
    # model the API does not list -- never "no": callers that gate on a
    # capability decide themselves whether unknown passes.
    # `cost_per_1k_tokens` stays the one blended rate the selection strategies
    # compare; these two are the real split, for cost estimates.
    prompt_cost_per_1k: float | None = None
    completion_cost_per_1k: float | None = None
    max_output_tokens: int | None = None  # top_provider.max_completion_tokens
    input_modalities: list[str] | None = None  # text, image, file, audio, video
    supported_parameters: list[str] | None = None  # tools, reasoning, temperature, ...
    # The model's `reasoning` object: accepted efforts, highest first. None when
    # the model exposes no effort selection. A mandatory-reasoning model rejects
    # `effort: "none"`.
    reasoning_efforts: list[str] | None = None
    reasoning_mandatory: bool | None = None
    expiration_date: str | None = None  # ISO date OpenRouter retires the model

    def _param(self, name: str) -> bool | None:
        return None if self.supported_parameters is None else name in self.supported_parameters

    @property
    def supports_tools(self) -> bool | None:
        return self._param("tools")

    @property
    def supports_structured_outputs(self) -> bool | None:
        return self._param("structured_outputs")

    @property
    def supports_temperature(self) -> bool | None:
        return self._param("temperature")

    @property
    def supports_reasoning(self) -> bool | None:
        return self._param("reasoning")

    @property
    def supports_vision(self) -> bool | None:
        return None if self.input_modalities is None else "image" in self.input_modalities

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

    def split_cost_per_1k(self) -> tuple[float, float]:
        """(prompt, completion) per 1k tokens; the blended rate when not known."""
        prompt = self.prompt_cost_per_1k
        completion = self.completion_cost_per_1k
        return (
            self.cost_per_1k_tokens if prompt is None else prompt,
            self.cost_per_1k_tokens if completion is None else completion,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        prompt, completion = self.split_cost_per_1k()
        return (input_tokens * prompt + output_tokens * completion) / 1000
