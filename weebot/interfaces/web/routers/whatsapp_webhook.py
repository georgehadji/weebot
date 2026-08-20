"""WhatsApp Business Cloud API webhook — FastAPI router.

Receives WhatsApp message events at ``POST /api/gateway/whatsapp/webhook``
and answers Meta's subscription verification handshake at
``GET /api/gateway/whatsapp/webhook``.

Flow:
1. GET handshake: Meta calls with ``hub.mode``/``hub.verify_token``/
   ``hub.challenge`` query params when the webhook is first registered;
   echo back the challenge if the verify token matches.
2. POST events: verify ``X-Hub-Signature-256`` (if an app secret is
   configured), ack immediately, and process/reply in the background —
   mirrors the Slack router's approach so a slow PlanActFlow run can't
   cause Meta to consider the webhook unhealthy.

Returns:
- ``401`` on invalid signature.
- ``403`` on failed verification handshake.
- ``503`` if the DI container (or WhatsApp credentials) is not configured.
- ``200`` on every valid, authenticated event.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gateway/whatsapp", tags=["whatsapp"])


@router.get("/webhook", response_model=None)
async def whatsapp_verify(request: Request):
    """Answer Meta's webhook subscription verification handshake."""
    adapter = _get_or_create_adapter(request)
    if adapter is None:
        raise HTTPException(
            status_code=503, detail="WhatsApp adapter not configured (missing credentials)"
        )

    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    verified, result = adapter.verify_webhook(mode, token, challenge)
    if not verified:
        raise HTTPException(status_code=403, detail=result)
    return Response(content=result, media_type="text/plain")


@router.post("/webhook", response_model=None)
async def whatsapp_events(request: Request):
    """Receive WhatsApp message events."""
    from weebot.application.di import Container

    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="DI container not initialized")

    adapter = _get_or_create_adapter(request)
    if adapter is None:
        raise HTTPException(
            status_code=503, detail="WhatsApp adapter not configured (missing credentials)"
        )

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not adapter.verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    messages = adapter.parse_incoming(payload)
    for msg in messages:
        asyncio.create_task(_handle_message(adapter, msg))

    return {"status": "ok"}


async def _handle_message(adapter, message) -> None:
    """Process a WhatsApp message and send the reply, off the request path."""
    from weebot.interfaces.gateways.base import GatewayResponse

    try:
        text = await adapter.process_message(message)
        if not text:
            return
        await adapter.send_response(
            GatewayResponse(text=text, platform="whatsapp", external_id=message.external_id)
        )
    except Exception as exc:
        logger.warning("WhatsApp message processing failed: %s", exc)


def _get_or_create_adapter(request: Request):
    """Return the cached WhatsAppAdapter or create one from settings."""
    adapter = getattr(request.app.state, "whatsapp_adapter", None)
    if adapter is not None:
        return adapter

    from weebot.application.di import Container
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.config.settings import WeebotSettings
    from weebot.interfaces.gateways.whatsapp import WhatsAppAdapter

    container: Container = request.app.state.container
    settings = WeebotSettings()

    if not settings.whatsapp_business_api_token or not settings.whatsapp_business_phone_number_id:
        logger.warning(
            "WhatsApp adapter not configured: set WHATSAPP_BUSINESS_API_TOKEN "
            "and WHATSAPP_BUSINESS_PHONE_NUMBER_ID in .env"
        )
        return None

    state_repo = container.get(StateRepositoryPort)
    llm = container.get(LLMPort)

    adapter = WhatsAppAdapter(
        token=settings.whatsapp_business_api_token,
        phone_number_id=settings.whatsapp_business_phone_number_id,
        state_repo=state_repo,
        llm=llm,
        webhook_verify_token=settings.whatsapp_webhook_verify_token,
        app_secret=settings.whatsapp_app_secret,
    )
    request.app.state.whatsapp_adapter = adapter
    return adapter
