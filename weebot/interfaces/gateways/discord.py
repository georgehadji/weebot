"""DiscordAdapter — receive and respond via Discord Interactions Endpoint.

Supports HTTP-based Interactions (slash commands) with Ed25519 signature
verification via ``pynacl``.  Uses a pure webhook model — no Discord
WebSocket gateway connection.

Incoming interactions flow:
  1. ``POST /api/gateway/discord/interactions`` receives the payload.
  2. Ed25519 signature is verified **before** any payload processing.
  3. ``PING`` (type 1) → immediate ``{"type": 1}`` PONG response.
  4. ``APPLICATION_COMMAND`` (type 2) → parsed, routed through
     PlanActFlow, response returned synchronously.
"""

from __future__ import annotations

import logging
import time

import aiohttp
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
    flow_session_id,
)

logger = logging.getLogger(__name__)

_MAX_SIGNATURE_AGE_S = 300  # replay window for signed interactions


class DiscordAdapter(GatewayAdapter):
    """Interactions Endpoint adapter for Discord slash commands.

    Args:
        public_key: Discord application public key (hex) for signature
            verification.
        bot_token: Discord bot token for REST API calls.
        application_id: Discord application / bot ID.
        state_repo: Session state repository for PlanActFlow.
        llm: LLM port for agent execution.
    """

    def __init__(
        self,
        public_key: str,
        bot_token: str,
        application_id: str,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        profile_name: str | None = None,
    ) -> None:
        super().__init__(llm_port=llm)
        self._public_key = public_key
        self._bot_token = bot_token
        self._application_id = application_id
        self._state_repo = state_repo
        self._llm = llm
        self._profile_name = profile_name
        self._verify_key = VerifyKey(bytes.fromhex(public_key))

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("DiscordAdapter started (app_id=%s, webhook-mode)", self._application_id[:8])

    async def stop(self) -> None:
        logger.info("DiscordAdapter stopped")

    # ── signature verification ──────────────────────────────────────

    def verify_signature(self, body: bytes, signature: str, timestamp: str) -> bool:
        """Validate Discord's Ed25519 signature on an incoming interaction.

        Args:
            body: Raw request body **before** any JSON parsing.
            signature: Value of the ``X-Signature-Ed25519`` header.
            timestamp: Value of the ``X-Signature-Timestamp`` header.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
        """
        try:
            # A signature proves who sent it, not when: without a freshness check a captured
            # request can be replayed forever.
            if abs(time.time() - int(timestamp)) > _MAX_SIGNATURE_AGE_S:
                logger.warning("Discord interaction timestamp outside the %ss window",
                               _MAX_SIGNATURE_AGE_S)
                return False
            # Decode with error tolerance — Discord always sends UTF-8 JSON
            # but malformed requests can carry non-UTF-8 bytes.
            body_str = body.decode("utf-8", errors="surrogateescape")
            self._verify_key.verify(f"{timestamp}{body_str}".encode(), bytes.fromhex(signature))
            return True
        except (BadSignatureError, ValueError, KeyError, TypeError, UnicodeError) as exc:
            logger.warning("Discord signature verification failed: %s", exc)
            return False

    # ── interaction parsing ─────────────────────────────────────────

    def parse_interaction(self, payload: dict) -> GatewayMessage | None:
        """Extract a ``GatewayMessage`` from a Discord interaction payload.

        Handles:
        - **Type 1 (PING):** Returns ``None`` — the caller (router) sends
          the immediate ``{"type": 1}`` PONG response.
        - **Type 2 (APPLICATION_COMMAND):** Builds a natural-language
          prompt from the command name and its options.

        Args:
            payload: Parsed JSON body of the interaction request.

        Returns:
            A ``GatewayMessage`` for type 2, ``None`` for PING or unknown types.
        """
        interaction_type = payload.get("type")
        if interaction_type == 1:  # PING
            return None

        if interaction_type != 2:  # APPLICATION_COMMAND
            logger.debug("Unhandled Discord interaction type: %s", interaction_type)
            return None

        data = payload.get("data", {})
        command_name = data.get("name", "")

        # Build a natural-language prompt from the command + resolved options
        options = data.get("options", [])
        option_text = " ".join(_format_option(opt) for opt in options)
        text = f"/{command_name} {option_text}".strip()

        channel_id = payload.get("channel_id", "")
        guild_id = payload.get("guild_id", "dm")
        user = payload.get("member", {}).get("user", payload.get("user", {}))

        return GatewayMessage(
            platform="discord",
            external_id=channel_id,
            text=text,
            metadata={
                "user_id": user.get("id", ""),
                "username": user.get("username", ""),
                "guild_id": guild_id,
                "interaction_token": payload.get("token", ""),
                "interaction_id": payload.get("id", ""),
                "application_id": payload.get("application_id", ""),
            },
        )

    # ── interaction processing ──────────────────────────────────────

    async def process_interaction(self, payload: dict) -> dict:
        """Process a validated interaction and return a Discord response payload.

        Args:
            payload: Parsed JSON body — the signature has already been
                verified by the caller.

        Returns:
            A dict suitable as the JSON response for Discord's interaction
            callback.  Always contains a ``"type"`` field.
        """
        # PING → immediate PONG
        if payload.get("type") == 1:
            return {"type": 1}

        msg = self.parse_interaction(payload)
        if msg is None:
            return {"type": 4, "data": {"content": "Sorry, I couldn't understand that command."}}

        user_id = msg.metadata.get("user_id", "")
        if not self.is_authorized("discord", msg.external_id, user_id):
            return {
                "type": 4,
                "data": {
                    "content": (
                        "This channel isn't authorized to use this bot. "
                        "Ask an admin to add it to the allowlist."
                    )
                },
            }

        text = await self.handle(msg)
        if text is None:
            return {"type": 4, "data": {"content": "Message blocked by safety check."}}
        reply = await self.handle_ponytail_command(text)
        if reply is not None:
            return {"type": 4, "data": {"content": reply}}

        # Discord drops an interaction not answered within 3 s, and a run takes longer:
        # answer "deferred" now and edit the reply when the run ends (audit R09).
        from weebot.core.background_tasks import get_background_tasks

        get_background_tasks().spawn(
            self._answer_later(msg, text), name=f"discord-{msg.metadata.get('interaction_id')}"
        )
        return {"type": 5}

    async def _answer_later(self, msg: GatewayMessage, text: str) -> None:
        """Run the flow, then put its last message (or a short error) in the deferred reply."""
        try:
            content = await self._run(msg, text)
        except Exception:
            logger.exception("Discord command failed in channel %s", msg.external_id)
            content = "Sorry, that command failed. Please try again."
        application_id = msg.metadata.get("application_id") or self._application_id
        # Discord message content limit is 2000 characters
        await self._edit_original(
            application_id, msg.metadata.get("interaction_token", ""), content[:2000]
        )

    async def _run(self, msg: GatewayMessage, text: str) -> str:
        from weebot.domain.models.session import Session
        from weebot.interfaces.factories import run_scope

        user_id = msg.metadata.get("user_id", "unknown")
        session_id = flow_session_id("discord", user_id)

        session = Session(id=session_id, user_id=f"discord-{user_id}", agent_id="discord-agent")

        response_text = ""
        async with run_scope(
            session, llm=self._llm, state_repo=self._state_repo, profile_name=self._profile_name
        ) as flow:
            async for event in flow.run(text):
                if getattr(event, "type", "") == "message":
                    response_text = getattr(event, "message", "") or response_text
        return response_text or "(no response produced)"

    async def _edit_original(self, application_id: str, token: str, content: str) -> bool:
        """Edit the deferred reply; the interaction token in the URL is the credential."""
        url = (
            f"https://discord.com/api/v10/webhooks/{application_id}/{token}/messages/@original"
        )
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.patch(url, json={"content": content}) as resp,
            ):
                if resp.status != 200:
                    logger.warning(
                        "Discord reply edit failed (HTTP %d): %s",
                        resp.status,
                        (await resp.text())[:200],
                    )
                return resp.status == 200
        except Exception as exc:
            logger.warning("Discord reply edit failed: %s", exc)
            return False

    # ── response sending (follow-up messages) ───────────────────────

    async def send_response(self, response: GatewayResponse) -> bool:
        """Send a follow-up message via Discord REST API.

        This is used for deferred responses or follow-ups.  The initial
        interaction response is returned synchronously from
        ``process_interaction()``.
        """
        if not response.success:
            return False

        url = f"https://discord.com/api/v10/channels/{response.external_id}/messages"
        headers = {"Authorization": f"Bot {self._bot_token}"}
        payload = {"content": response.text[:2000]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        error_body = await resp.text()
                        logger.warning(
                            "Discord send failed (HTTP %d): %s", resp.status, error_body[:200]
                        )
                    return resp.status == 200
        except Exception as exc:
            logger.warning("Discord send failed: %s", exc)
            return False


# ── helper ──────────────────────────────────────────────────────────


def _format_option(opt: dict) -> str:
    """Format a Discord option for the natural-language prompt."""
    name = opt.get("name", "")
    value = opt.get("value", "")
    # Sub-command groups have nested options
    if "options" in opt:
        children = " ".join(_format_option(o) for o in opt["options"])
        return f"{name}: {children}"
    return f"{name}: {value}"
