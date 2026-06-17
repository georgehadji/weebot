"""Signal Gateway — send and receive messages via signal-cli REST API.

Uses signal-cli's JSON-RPC or REST API (signald or signal-cli-rest-api)
to send and receive messages.  Requires a local signal-cli instance.

Configuration (in .env):
    SIGNAL_CLI_REST_URL=http://localhost:8080
    SIGNAL_ACCOUNT_NUMBER=+1234567890
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
)

logger = logging.getLogger(__name__)


class SignalAdapter(GatewayAdapter):
    """Adapter for Signal messaging via signal-cli REST API."""

    def __init__(
        self,
        rest_url: str = "http://localhost:8080",
        account_number: str | None = None,
    ) -> None:
        super().__init__()
        self._rest_url = rest_url.rstrip("/")
        self._account_number = account_number
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("SignalAdapter started (account: %s)", self._account_number)

    async def stop(self) -> None:
        self._running = False
        logger.info("SignalAdapter stopped")

    async def send_response(self, response: GatewayResponse) -> bool:
        """Send a message via signal-cli."""
        if not response.success:
            return False

        url = f"{self._rest_url}/v2/send"
        payload = {
            "message": response.text[:5000],
            "number": self._account_number,
            "recipients": [response.external_id],
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status not in (200, 201):
                        error_body = await resp.text()
                        logger.warning("Signal send failed (HTTP %d): %s", resp.status, error_body[:200])
                        return False
                    return True
        except Exception as exc:
            logger.warning("Signal send error: %s", exc)
            return False

    async def receive_messages(self) -> list[GatewayMessage]:
        """Poll for incoming Signal messages.

        Returns list of new GatewayMessages.
        """
        messages: list[GatewayMessage] = []

        url = f"{self._rest_url}/v1/receive/{self._account_number}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params={"timeout": 10}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data if isinstance(data, list) else [data]:
                            envelope = item.get("envelope", {})
                            sender = envelope.get("source", "")
                            data_message = envelope.get("dataMessage", {})
                            text = data_message.get("message", "")
                            if sender and text:
                                messages.append(GatewayMessage(
                                    platform="signal",
                                    external_id=sender,
                                    text=text.strip(),
                                    metadata={
                                        "timestamp": envelope.get("timestamp"),
                                        "message_id": data_message.get("timestamp"),
                                    },
                                ))
        except Exception as exc:
            logger.debug("Signal receive error (may be normal): %s", exc)

        return messages
