"""SlackAdapter — receive and respond via Slack Events API + Webhooks.

Supports both incoming webhooks (Events API) and direct message posting
via chat.postMessage. Validates HMAC signatures on incoming events.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

import aiohttp

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.interfaces.factories import build_tools, create_flow
from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
)

logger = logging.getLogger(__name__)


class SlackAdapter(GatewayAdapter):
    """Events API + Webhook adapter for Slack messaging."""

    def __init__(
        self,
        signing_secret: str,
        bot_token: str,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
    ) -> None:
        super().__init__()
        self._signing_secret = signing_secret
        self._bot_token = bot_token
        self._state_repo = state_repo
        self._llm = llm

    async def start(self) -> None:
        logger.info("SlackAdapter started (webhook-mode, no polling needed)")

    async def stop(self) -> None:
        logger.info("SlackAdapter stopped")

    def verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        """Validate Slack's HMAC-SHA256 signature on incoming events."""
        if abs(time.time() - int(timestamp)) > 300:
            logger.warning("Slack signature timestamp too old")
            return False

        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
        expected = (
            "v0="
            + hmac.new(
                self._signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(expected, signature)

    def parse_event(self, payload: dict) -> Optional[GatewayMessage]:
        """Extract a GatewayMessage from a Slack Events API payload."""
        event = payload.get("event", {})
        if event.get("type") == "url_verification":
            return None  # Handled separately

        text = event.get("text", "")
        channel = event.get("channel", "")
        user = event.get("user", "")

        if not text or not channel:
            return None

        return GatewayMessage(
            platform="slack",
            external_id=channel,
            text=self._strip_mentions(text),
            metadata={
                "user": user,
                "team": payload.get("team_id", ""),
                "ts": event.get("ts", ""),
            },
        )

    @staticmethod
    def _strip_mentions(text: str) -> str:
        """Remove <@USER_ID> mentions from Slack text."""
        import re

        return re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    async def process_event(self, payload: dict) -> Optional[str]:
        """Process a validated Slack event and return a response."""
        msg = self.parse_event(payload)
        if msg is None:
            return None

        text = await self.handle(msg)
        if text is None:
            return "Message blocked by safety check."

        import uuid

        session_id = f"slack-{msg.external_id}-{uuid.uuid4().hex[:6]}"
        from weebot.domain.models.session import Session

        session = Session(
            id=session_id,
            user_id=f"slack-{msg.external_id}",
            agent_id="slack-agent",
        )

        tools = await build_tools(role="admin")
        flow = create_flow(
            flow_type="plan_act",
            session=session,
            llm=self._llm,
            tools=tools,
            state_repo=self._state_repo,
        )

        response = ""
        async for event in flow.run(text):
            if getattr(event, "type", "") == "message":
                response = getattr(event, "message", "") or response

        return response or "(no response)"

    async def send_response(self, response: GatewayResponse) -> bool:
        if not response.success:
            return False
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {self._bot_token}"}
        payload = {"channel": response.external_id, "text": response.text[:3000]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers
                ) as resp:
                    return resp.status == 200
        except Exception as exc:
            logger.warning("Slack send failed: %s", exc)
            return False
