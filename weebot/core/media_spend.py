"""Spend by calls that are not chat completions: image and video generation.

A paid 200 from a media model is an LLMCallCompleted like any other, so the session meter
and its limits see it. The tools sit below the container, so the container registers one
sink at startup and the tools only call ``record_media_call``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from weebot.config.model_refs import MEDIA_CALL_USD, MEDIA_CALL_USD_DEFAULT
from weebot.core.log_context import session_id_var
from weebot.domain.models.event import LLMCallCompleted

logger = logging.getLogger(__name__)

# One slot, mutated in place: the DI container registers the sink once per process.
_sink: list[Callable[[Any], Awaitable[None]]] = []


def set_media_spend_sink(sink: Callable[[Any], Awaitable[None]] | None) -> None:
    _sink[:] = [sink] if sink else []


def media_call_usd(model: str, kind: str) -> float:
    return MEDIA_CALL_USD.get(model, MEDIA_CALL_USD_DEFAULT.get(kind, 0.0))


async def record_media_call(model: str, kind: str) -> None:
    """Report one paid media request; never raises into the tool."""
    if not _sink:
        return
    try:
        await _sink[0](
            LLMCallCompleted(
                session_id=session_id_var.get() or "",
                model=model,
                cost=media_call_usd(model, kind),
                estimated=True,
            )
        )
    except Exception:
        logger.warning("media spend hook failed for %s", model, exc_info=True)
