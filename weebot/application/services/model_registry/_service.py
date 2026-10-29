"""Model selection service — strategy-based routing to optimal LLM.

Extracted from ``model_selection.py`` during WP-2 god module decomposition.
This module references the catalog data from ``model_catalog.py`` and the
selection strategies from ``_strategies.py``.
"""

from __future__ import annotations

from weebot.config.model_catalog import MODELS
from weebot.config.secret_accessor import SecretAccessor
from weebot.domain.models.model_config import ModelConfig
from weebot.application.services.model_registry._strategies import ModelSelectionStrategy
from weebot.domain.models.task_type import TaskType


class ModelSelectionService:
    """Service for selecting the optimal LLM model and creating adapters."""

    MODELS: dict[str, ModelConfig] = MODELS  # Reference the catalog

    def _usable(self) -> list[tuple[str, ModelConfig]]:
        """Catalog models that can be called now: a key is set, or none is needed (local)."""
        from weebot.config.free_models import free_models
        from weebot.config.local_models import local_models

        catalog = {**self.MODELS, **local_models(), **free_models()}
        return [
            (model_id, cfg)
            for model_id, cfg in catalog.items()
            if not cfg.api_key_env or SecretAccessor.get(cfg.api_key_env)
        ]

    def available_models(self) -> list[str]:
        """Return model IDs for which the API key is configured."""
        return [model_id for model_id, _ in self._usable()]

    def select_model(
        self, strategy: ModelSelectionStrategy, task_type: TaskType, budget: float | None = None
    ) -> str:
        """Select a model using the provided strategy."""
        candidates = self._usable()
        if not candidates:
            raise ValueError("No API keys configured for any supported provider")
        return strategy.select(candidates, task_type, budget)

    # `create_llm_adapter` used to live here: it constructed an adapter through
    # infrastructure and returned it unwrapped. Two problems in one method (WB-01,
    # WB-02): an application service reaching into infrastructure, and a second
    # construction site outside the container, so the port reached the executor
    # without the global LLM bulkhead around it. Getting a port for a model is the
    # composition root's job now -- `Container.create_llm_for_model(model_id)`.

