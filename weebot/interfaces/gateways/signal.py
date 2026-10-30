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

import aiohttp

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
    PollBackoff,
    flow_session_id,
)

logger = logging.getLogger(__name__)


class SignalAdapter(GatewayAdapter):
    """Adapter for Signal messaging via signal-cli REST API."""

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        rest_url: str = "http://localhost:8080",
        account_number: str | None = None,
        profile_name: str | None = None,
    ) -> None:
        super().__init__(llm_port=llm)
        self._rest_url = rest_url.rstrip("/")
        self._account_number = account_number
        self._state_repo = state_repo
        self._llm = llm
        self._profile_name = profile_name
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("SignalAdapter started (account: %s)", self._account_number)

    async def stop(self) -> None:
        self._running = False
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        logger.info("SignalAdapter stopped")

    async def _poll_loop(self) -> None:
        backoff = PollBackoff()
        while self._running:
            try:
                messages = await self.receive_messages()
            except Exception as exc:
                logger.error("Signal poll error: %s", exc)
                await asyncio.sleep(backoff.next_delay())
                continue
            backoff.reset()
            for msg in messages:
                try:
                    text = await self._process_message(msg)
                    if text:
                        await self.send_response(
                            GatewayResponse(
                                text=text, platform="signal", external_id=msg.external_id
                            )
                        )
                except Exception as exc:
                    logger.warning("Error processing Signal message: %s", exc)

    async def _process_message(self, message: GatewayMessage) -> str:
        """Run an inbound Signal message through PlanActFlow.

        Returns the response text, or ``""`` if the message was dropped
        (unauthorized sender or safety block).
        """
        if not self.is_authorized("signal", message.external_id):
            logger.warning(
                "Signal message rejected by gateway allowlist: from=%s", message.external_id
            )
            return ""

        text = await self.handle(message)
        if text is None:
            return "Message blocked by safety check."
        reply = await self.handle_ponytail_command(text)
        if reply is not None:
            return reply

        from weebot.domain.models.session import Session
        from weebot.interfaces.factories import run_scope

        session_id = flow_session_id("signal", message.external_id)
        session = Session(
            id=session_id, user_id=f"signal-{message.external_id}", agent_id="signal-agent"
        )

        response = ""
        async with run_scope(
            session, llm=self._llm, state_repo=self._state_repo, profile_name=self._profile_name
        ) as flow:
            async for event in flow.run(text):
                if getattr(event, "type", "") == "message":
                    response = getattr(event, "message", "") or response

        return response or "(no response produced)"

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
                        logger.warning(
                            "Signal send failed (HTTP %d): %s", resp.status, error_body[:200]
                        )
                        return False
                    return True
        except Exception as exc:
            logger.warning("Signal send error: %s", exc)
            return False

    async def receive_messages(self) -> list[GatewayMessage]:
        """Poll for incoming Signal messages.

        Returns list of new GatewayMessages. Raises when signal-cli cannot be reached or
        answers with an error, so the poll loop backs off instead of spinning (R10).
        """
        messages: list[GatewayMessage] = []

        url = f"{self._rest_url}/v1/receive/{self._account_number}"
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, params={"timeout": 10}) as resp,
        ):
            if resp.status != 200:
                raise RuntimeError(f"signal-cli receive answered HTTP {resp.status}")
            data = await resp.json()
        for item in data if isinstance(data, list) else [data]:
            envelope = item.get("envelope", {})
            sender = envelope.get("source", "")
            data_message = envelope.get("dataMessage", {})
            text = data_message.get("message", "")
            if sender and text:
                messages.append(
                    GatewayMessage(
                        platform="signal",
                        external_id=sender,
                        text=text.strip(),
                        metadata={
                            "timestamp": envelope.get("timestamp"),
                            "message_id": data_message.get("timestamp"),
                        },
                    )
                )
        return messages
