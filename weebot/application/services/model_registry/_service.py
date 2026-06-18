"""Model selection service — strategy-based routing to optimal LLM.

Extracted from ``model_selection.py`` during WP-2 god module decomposition.
This module references the catalog data from ``_catalog.py`` and the
selection strategies from ``_strategies.py``.
"""
from __future__ import annotations

import os
from typing import List, Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.services.model_registry._catalog import MODELS
from weebot.application.services.model_registry._models import ModelConfig
from weebot.application.services.model_registry._strategies import ModelSelectionStrategy
from weebot.domain.models.task_type import TaskType


class ModelSelectionService:
    """Service for selecting the optimal LLM model and creating adapters."""

    MODELS: dict[str, ModelConfig] = MODELS  # Reference the catalog

    def available_models(self) -> List[str]:
        """Return model IDs for which the API key is configured."""
        return [
            model_id
            for model_id, cfg in self.MODELS.items()
            if os.getenv(cfg.api_key_env)
        ]

    def select_model(
        self,
        strategy: ModelSelectionStrategy,
        task_type: TaskType,
        budget: Optional[float] = None,
    ) -> str:
        """Select a model using the provided strategy."""
        candidates = [
            (mid, cfg)
            for mid, cfg in self.MODELS.items()
            if os.getenv(cfg.api_key_env)
        ]
        if not candidates:
            raise ValueError("No API keys configured for any supported provider")
        return strategy.select(candidates, task_type, budget)

    def create_llm_adapter(self, model_id: str) -> LLMPort:
        """Instantiate the correct LLMPort adapter for a model ID."""
        import os
        from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter

        config = self.MODELS.get(model_id)
        if not config:
            raise ValueError(f"Unknown model: {model_id}")

        provider = "openrouter"
        api_key = os.getenv("OPENROUTER_API_KEY")
        return create_adapter(provider, model=model_id, api_key=api_key)
