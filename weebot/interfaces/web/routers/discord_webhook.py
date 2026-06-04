"""Discord interactions webhook — FastAPI router.

Receives Discord interaction events at ``POST /api/gateway/discord/interactions``.

Signature verification flow:
1. Read raw body bytes **before** JSON parsing (needed for Ed25519).
2. Verify ``X-Signature-Ed25519`` + ``X-Signature-Timestamp`` headers.
3. Route to ``DiscordAdapter.process_interaction()``.

Returns:
- ``401`` on invalid signature.
- ``503`` if the DI container is not initialized.
- ``200`` with a Discord interaction response on success.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gateway/discord", tags=["discord"])


@router.post("/interactions", response_model=None)
async def discord_interactions(request: Request):
    """Receive Discord interaction events.

    Discord sends interactions as JSON ``POST`` requests.  We verify the
    Ed25519 signature, return an immediate PONG for type 1 (PING), and
    process type 2 (APPLICATION_COMMAND) through the DiscordAdapter.
    """
    from weebot.application.di import Container

    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="DI container not initialized")

    body = await request.body()
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    payload = await request.json()

    # Lazy-init adapter singleton on app state
    adapter = _get_or_create_adapter(request)
    if adapter is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Discord adapter not configured (missing credentials)"},
        )

    if not adapter.verify_signature(body, signature, timestamp):
        raise HTTPException(status_code=401, detail="Invalid signature")

    result = await adapter.process_interaction(payload)
    return result


def _get_or_create_adapter(request: Request):
    """Return the cached DiscordAdapter or create one from settings."""
    adapter = getattr(request.app.state, "discord_adapter", None)
    if adapter is not None:
        return adapter

    from weebot.application.di import Container
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.config.settings import WeebotSettings
    from weebot.interfaces.gateways.discord import DiscordAdapter

    container: Container = request.app.state.container
    settings = WeebotSettings()

    if not settings.discord_public_key or not settings.discord_bot_token:
        logger.warning(
            "Discord adapter not configured: set DISCORD_PUBLIC_KEY "
            "and DISCORD_BOT_TOKEN in .env"
        )
        return None

    state_repo = container.get(StateRepositoryPort)
    llm = container.get(LLMPort)

    adapter = DiscordAdapter(
        public_key=settings.discord_public_key,
        bot_token=settings.discord_bot_token,
        application_id=settings.discord_application_id or "",
        state_repo=state_repo,
        llm=llm,
    )
    request.app.state.discord_adapter = adapter
    return adapter
