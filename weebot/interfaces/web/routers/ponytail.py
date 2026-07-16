"""Web API routes for Ponytail lazy-senior-dev mode.

Exposes read/write access to the active Ponytail intensity so web users and
gateway bots can inspect or toggle it.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from cli.commands.ponytail import read_ponytail_mode, write_ponytail_mode

router = APIRouter(prefix="/ponytail", tags=["ponytail"])

_ALLOWED_MODES = {"off", "lite", "full", "ultra"}


@router.get("/mode")
async def get_ponytail_mode() -> dict[str, str]:
    """Return the currently active Ponytail mode."""
    return {"mode": read_ponytail_mode()}


@router.post("/mode/{mode}")
async def set_ponytail_mode(mode: str) -> dict[str, str]:
    """Set the Ponytail mode to off, lite, full, or ultra."""
    normalized = mode.strip().lower()
    if normalized not in _ALLOWED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {_ALLOWED_MODES}",
        )
    await asyncio.to_thread(write_ponytail_mode, normalized)
    return {"mode": normalized}
