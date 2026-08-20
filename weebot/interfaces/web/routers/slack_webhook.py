"""Slack Events API webhook — FastAPI router.

Receives Slack Events API callbacks at ``POST /api/gateway/slack/events``.

Flow:
1. Read raw body bytes **before** JSON parsing (needed for HMAC verification).
2. Verify ``X-Slack-Signature`` + ``X-Slack-Request-Timestamp`` headers.
3. Answer Slack's ``url_verification`` handshake directly.
4. Ack with ``200`` immediately, then process the event in the background
   and post the reply via ``chat.postMessage`` — Slack retries any event
   that isn't acknowledged within ~3 seconds, and a PlanActFlow run can
   easily take longer than that.

Returns:
- ``401`` on invalid signature.
- ``503`` if the DI container (or Slack credentials) is not configured.
- ``200`` on every valid, authenticated event.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gateway/slack", tags=["slack"])


@router.post("/events", response_model=None)
async def slack_events(request: Request):
    """Receive Slack Events API callbacks."""
    from weebot.application.di import Container

    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="DI container not initialized")

    body = await request.body()
    payload = await request.json()

    # The URL verification handshake is unsigned at setup time in some
    # Slack app configs — answer it before requiring an adapter/signature.
    if payload.get("type") == "url_verification":
        return JSONResponse(content={"challenge": payload.get("challenge", "")})

    adapter = _get_or_create_adapter(request)
    if adapter is None:
        return JSONResponse(
            status_code=503, content={"error": "Slack adapter not configured (missing credentials)"}
        )

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not timestamp or not signature or not adapter.verify_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Slack retries the same event if it doesn't see 200 within ~3s. We
    # already acked, so a retry means our first ack was lost in transit —
    # skip reprocessing to avoid answering the same message twice.
    if request.headers.get("X-Slack-Retry-Num"):
        return JSONResponse(content={"ok": True})

    asyncio.create_task(_handle_event(adapter, payload))
    return JSONResponse(content={"ok": True})


async def _handle_event(adapter, payload: dict) -> None:
    """Process a Slack event and post the reply, off the request path."""
    from weebot.interfaces.gateways.base import GatewayResponse

    try:
        text = await adapter.process_event(payload)
        if not text:
            return
        channel = payload.get("event", {}).get("channel", "")
        if not channel:
            return
        await adapter.send_response(
            GatewayResponse(text=text, platform="slack", external_id=channel)
        )
    except Exception as exc:
        logger.warning("Slack event processing failed: %s", exc)


def _get_or_create_adapter(request: Request):
    """Return the cached SlackAdapter or create one from settings."""
    adapter = getattr(request.app.state, "slack_adapter", None)
    if adapter is not None:
        return adapter

    from weebot.application.di import Container
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.config.settings import WeebotSettings
    from weebot.interfaces.gateways.slack import SlackAdapter

    container: Container = request.app.state.container
    settings = WeebotSettings()

    if not settings.slack_signing_secret or not settings.slack_bot_token:
        logger.warning(
            "Slack adapter not configured: set SLACK_BOT_TOKEN " "and SLACK_SIGNING_SECRET in .env"
        )
        return None

    state_repo = container.get(StateRepositoryPort)
    llm = container.get(LLMPort)

    adapter = SlackAdapter(
        signing_secret=settings.slack_signing_secret,
        bot_token=settings.slack_bot_token,
        state_repo=state_repo,
        llm=llm,
    )
    request.app.state.slack_adapter = adapter
    return adapter
