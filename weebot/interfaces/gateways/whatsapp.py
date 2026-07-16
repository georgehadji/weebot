"""WhatsApp Gateway — send and receive messages via WhatsApp Business Cloud API.

Uses the WhatsApp Business Cloud API (v19.0) for reliable message delivery.
Supports text, image, document, and interactive message types.

Requires WHATSAPP_BUSINESS_API_TOKEN and WHATSAPP_BUSINESS_PHONE_NUMBER_ID
in .env configuration.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any

import aiohttp

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
)

logger = logging.getLogger(__name__)


class WhatsAppAdapter(GatewayAdapter):
    """Adapter for WhatsApp Business Cloud API messaging."""

    API_BASE = "https://graph.facebook.com/v19.0"

    def __init__(
        self,
        token: str,
        phone_number_id: str,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        webhook_verify_token: str | None = None,
        app_secret: str | None = None,
        profile_name: str | None = None,
    ) -> None:
        super().__init__(llm_port=llm)
        self._token = token
        self._phone_number_id = phone_number_id
        self._webhook_verify_token = webhook_verify_token or "weebot-verify"
        self._app_secret = app_secret
        self._state_repo = state_repo
        self._llm = llm
        self._profile_name = profile_name
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("WhatsAppAdapter started (phone: %s)", self._phone_number_id)

    async def stop(self) -> None:
        self._running = False
        logger.info("WhatsAppAdapter stopped")

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Validate Meta's ``X-Hub-Signature-256`` header on incoming webhooks.

        Returns ``True`` (unverified) if no app secret is configured, since
        signature verification is optional for the WhatsApp Cloud API.
        """
        if not self._app_secret:
            logger.warning(
                "WHATSAPP_APP_SECRET not configured — accepting webhook without "
                "signature verification"
            )
            return True
        if not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(
            self._app_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def process_message(self, message: GatewayMessage) -> str:
        """Run an inbound WhatsApp message through PlanActFlow.

        Returns the response text, or ``""`` if the message was dropped
        (unauthorized sender or safety block).
        """
        if not self.is_authorized("whatsapp", message.external_id):
            logger.warning(
                "WhatsApp message rejected by gateway allowlist: from=%s",
                message.external_id,
            )
            return ""

        text = await self.handle(message)
        if text is None:
            return "Message blocked by safety check."

        import uuid

        from weebot.domain.models.session import Session
        from weebot.interfaces.factories import build_tools, create_flow

        session_id = f"whatsapp-{message.external_id}-{uuid.uuid4().hex[:6]}"
        session = Session(
            id=session_id,
            user_id=f"whatsapp-{message.external_id}",
            agent_id="whatsapp-agent",
        )

        tools = await build_tools(role="admin")
        flow = create_flow(
            flow_type="plan_act",
            session=session,
            llm=self._llm,
            tools=tools,
            state_repo=self._state_repo,
            profile_name=self._profile_name,
        )

        response = ""
        async for event in flow.run(text):
            if getattr(event, "type", "") == "message":
                response = getattr(event, "message", "") or response

        return response or "(no response produced)"

    async def send_response(self, response: GatewayResponse) -> bool:
        """Send a text message back to a WhatsApp user."""
        if not response.success:
            return False

        url = f"{self.API_BASE}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": response.external_id,
            "type": "text",
            "text": {"body": response.text[:4096]},
        }

        try:
            async with aiohttp.ClientSession(headers=self._headers) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status not in (200, 201):
                        error_body = await resp.text()
                        logger.warning("WhatsApp send failed (HTTP %d): %s", resp.status, error_body[:200])
                        return False
                    return True
        except Exception as exc:
            logger.warning("WhatsApp send error: %s", exc)
            return False

    def verify_webhook(self, mode: str, token: str, challenge: str) -> tuple[bool, str]:
        """Verify the WhatsApp webhook challenge.

        Called by the web framework during webhook registration.
        Returns (verified, challenge_or_reason).
        """
        if mode == "subscribe" and token == self._webhook_verify_token:
            return True, challenge
        return False, "Verification failed"

    def parse_incoming(self, body: dict[str, Any]) -> list[GatewayMessage]:
        """Parse a WhatsApp webhook payload into GatewayMessage objects.

        Args:
            body: The webhook request body from WhatsApp.

        Returns:
            List of GatewayMessage objects (usually 0 or 1).
        """
        messages: list[GatewayMessage] = []

        try:
            entries = body.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    if "messages" not in value:
                        continue
                    for msg in value["messages"]:
                        msg_from = msg.get("from", "")
                        msg_text = ""
                        if msg.get("type") == "text":
                            msg_text = msg.get("text", {}).get("body", "")
                        elif msg.get("type") == "interactive":
                            msg_text = msg.get("interactive", {}).get("button_reply", {}).get("title", "")
                        if msg_text and msg_from:
                            messages.append(GatewayMessage(
                                platform="whatsapp",
                                external_id=msg_from,
                                text=msg_text.strip(),
                                metadata={
                                    "message_id": msg.get("id"),
                                    "msg_type": msg.get("type"),
                                    "timestamp": msg.get("timestamp"),
                                },
                            ))
        except Exception as exc:
            logger.error("Failed to parse WhatsApp webhook: %s", exc)

        return messages


class WhatsAppWebhookHandler:
    """Handles WhatsApp webhook verification and message receipt.

    Integrates with FastAPI or similar framework.
    """

    def __init__(self, adapter: WhatsAppAdapter) -> None:
        self._adapter = adapter

    async def handle_webhook(self, body: dict[str, Any]) -> list[GatewayMessage]:
        """Process an incoming WhatsApp webhook payload."""
        return self._adapter.parse_incoming(body)
