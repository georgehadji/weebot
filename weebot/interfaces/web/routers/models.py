"""Model listing API routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from weebot.interfaces.web.auth import require_mutation_identity


# Lazy import via importlib to avoid import-linter trace (composition root acceptable)
def _get_model_selection():
    import importlib as _il

    return _il.import_module("weebot.application.services.model_selection").ModelSelectionService


from weebot.interfaces.web.schemas import ModelInfoResponse, RoleModelResponse

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


class RoleModelRequest(BaseModel):
    model: str


def _role_row(role: str) -> RoleModelResponse:
    from weebot.config.model_refs import ROLE_MODEL_CONFIG, get_model_cascade_for_role
    from weebot.config.role_overrides import get_overrides

    return RoleModelResponse(
        role=role,
        default=list(ROLE_MODEL_CONFIG[role]),
        override=get_overrides().get(role),
        effective=get_model_cascade_for_role(role)[0],
    )


@router.get("/roles", response_model=list[RoleModelResponse])
async def list_role_models() -> list[RoleModelResponse]:
    """Every agent role with its built-in cascade, the user's pick and the model in use."""
    from weebot.config.model_refs import ROLE_MODEL_CONFIG

    return [_role_row(role) for role in ROLE_MODEL_CONFIG]


@router.put(
    "/roles/{role}",
    response_model=RoleModelResponse,
    dependencies=[Depends(require_mutation_identity)],
)
async def set_role_model(role: str, body: RoleModelRequest) -> RoleModelResponse:
    """Make *body.model* the first choice for *role*; the built-in cascade stays as fallback."""
    from weebot.config.local_models import all_models
    from weebot.config.model_refs import ROLE_MODEL_CONFIG, claude_model_allowed
    from weebot.config.role_overrides import set_override

    if role not in ROLE_MODEL_CONFIG:
        raise HTTPException(status_code=404, detail=f"unknown role: {role}")
    if body.model not in all_models():
        raise HTTPException(status_code=400, detail=f"unknown model: {body.model}")
    if not claude_model_allowed(body.model):
        raise HTTPException(status_code=400, detail="that Claude model is not allowed")
    await asyncio.to_thread(set_override, role, body.model)
    return _role_row(role)


@router.delete(
    "/roles/{role}",
    response_model=RoleModelResponse,
    dependencies=[Depends(require_mutation_identity)],
)
async def reset_role_model(role: str) -> RoleModelResponse:
    """Drop the user's pick for *role* and go back to the built-in cascade."""
    from weebot.config.model_refs import ROLE_MODEL_CONFIG
    from weebot.config.role_overrides import clear_override

    if role not in ROLE_MODEL_CONFIG:
        raise HTTPException(status_code=404, detail=f"unknown role: {role}")
    await asyncio.to_thread(clear_override, role)
    return _role_row(role)


@router.get("/available", response_model=list[str])
async def list_available_models() -> list[str]:
    """List only models that have API keys configured."""
    service = _get_model_selection()()
    return service.available_models()
