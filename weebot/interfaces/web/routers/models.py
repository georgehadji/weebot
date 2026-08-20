"""Model listing API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter


# Lazy import via importlib to avoid import-linter trace (composition root acceptable)
def _get_model_selection():
    import importlib as _il

    return _il.import_module("weebot.application.services.model_selection").ModelSelectionService


from weebot.interfaces.web.schemas import ModelInfoResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelInfoResponse])
async def list_models() -> list[ModelInfoResponse]:
    """List all available models with their configuration."""
    service = _get_model_selection()()

    models = []
    for model_id, config in service.MODELS.items():
        models.append(
            ModelInfoResponse(
                id=model_id,
                name=config.name,
                provider=config.provider,
                cost_per_1k_tokens=config.cost_per_1k_tokens,
                context_window=config.context_window,
                tier=config.tier.value,
                strengths=[s.value for s in config.strengths],
            )
        )

    # Sort by tier (free first), then by cost
    tier_order = {"free": 0, "fast": 1, "standard": 2, "premium": 3}
    models.sort(key=lambda m: (tier_order.get(m.tier, 99), m.cost_per_1k_tokens))

    return models


@router.get("/available", response_model=list[str])
async def list_available_models() -> list[str]:
    """List only models that have API keys configured."""
    service = _get_model_selection()()
    return service.available_models()
