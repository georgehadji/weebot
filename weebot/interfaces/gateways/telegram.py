"""TelegramAdapter — receive and respond to messages via Telegram Bot API.

Uses long-polling (getUpdates) to receive messages. Normalizes incoming
messages into GatewayMessage and routes responses back via sendMessage.

Session continuity (Track 2 — Hermes Audit):
    Each incoming message is resolved against a GatewaySessionKey derived
    from the chat ID, so subsequent messages in the same chat resume the
    same Weebot flow session. Slash commands (/new, /reset, /help, etc.)
    are handled by the GatewayCommandDispatcher without invoking the LLM.

Requires TELEGRAM_BOT_TOKEN in .env.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiohttp

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.gateway_command_dispatcher import (
    GatewayCommandDispatcher,
    build_default_dispatcher,
)
from weebot.application.services.gateway_flow_resolver import GatewayFlowResolver
from weebot.domain.models.gateway_session import GatewaySessionKey
from weebot.domain.models.session import Session
from weebot.interfaces.factories import run_scope
from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
    PollBackoff,
)

logger = logging.getLogger(__name__)


class TelegramApiError(Exception):
    """getUpdates answered ``ok: false`` (audit R10)."""

    def __init__(self, code: int, description: str, retry_after: float | None) -> None:
        super().__init__(f"Telegram API error {code}: {description}")
        self.code = code
        self.retry_after = retry_after


class TelegramAdapter(GatewayAdapter):
    """Bot API adapter for Telegram messaging with session continuity."""

    def __init__(
        self,
        token: str,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        flow_resolver: GatewayFlowResolver,
        profile_name: str | None = None,
        command_dispatcher: GatewayCommandDispatcher | None = None,
    ) -> None:
        super().__init__(llm_port=llm)
        self._token = token
        self._api = f"https://api.telegram.org/bot{token}"
        self._state_repo = state_repo
        self._llm = llm
        self._flow_resolver = flow_resolver
        self._command_dispatcher = command_dispatcher or build_default_dispatcher()
        self._profile_name = profile_name
        self._offset = 0
        self._running = False
        # Track active sessions: chat_id -> (GatewaySession, flow_session_id)
        self._active_sessions: dict[str, tuple] = {}
        # One run at a time per chat, as a task, so the poll loop keeps reading (/stop).
        self._runs: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("TelegramAdapter started")

    async def stop(self) -> None:
        self._running = False
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        for chat in list(self._runs):
            await self._stop_run(chat)
        logger.info("TelegramAdapter stopped")

    async def _poll_loop(self) -> None:
        backoff = PollBackoff()
        while self._running:
            try:
                updates = await self._get_updates()
            except TelegramApiError as exc:
                if exc.code == 401:  # a rejected token does not get better by asking again
                    logger.error("Telegram polling stopped: %s", exc)
                    self._running = False
                    return
                logger.warning("Telegram poll error: %s", exc)
                await asyncio.sleep(backoff.next_delay(exc.retry_after))
                continue
            except Exception as exc:
                logger.error("Telegram poll error: %s", exc)
                await asyncio.sleep(backoff.next_delay())
                continue
            backoff.reset()
            for update in updates:
                try:
                    msg = self._parse_update(update)
                    if msg:
                        response_text = await self._process_message(msg)
                        if response_text is not None:  # None: a run started and replies itself
                            await self._reply(msg.external_id, response_text)
                except Exception as exc:
                    logger.warning("Error processing Telegram message: %s", exc)

    async def _get_updates(self) -> list[dict]:
        """New updates; raises TelegramApiError when the API answers ``ok: false``."""
        url = f"{self._api}/getUpdates"
        params = {"offset": self._offset, "timeout": 30}
        async with aiohttp.ClientSession() as session, session.get(url, params=params) as resp:
            data = await resp.json(content_type=None)
            if data.get("ok"):
                return data.get("result", [])
            raise TelegramApiError(
                int(data.get("error_code") or resp.status),
                str(data.get("description", "")),
                (data.get("parameters") or {}).get("retry_after"),
            )

    def _parse_update(self, update: dict) -> GatewayMessage | None:
        msg = update.get("message", {})
        text = msg.get("text", "")
        chat = msg.get("chat", {})
        chat_id = chat.get("id", 0)

        self._offset = max(self._offset, update.get("update_id", 0) + 1)

        if not text or not chat_id:
            return None

        sender = msg.get("from", {})

        return GatewayMessage(
            platform="telegram",
            external_id=str(chat_id),
            text=text.strip(),
            metadata={
                "message_id": msg.get("message_id"),
                "user_id": str(sender.get("id", "")),
                "username": chat.get("username", ""),
                "first_name": chat.get("first_name", ""),
                "chat_type": chat.get("type", ""),
                "chat_title": chat.get("title", ""),
                "is_topic_message": msg.get("is_topic_message", False),
                "message_thread_id": msg.get("message_thread_id"),
                "chat": dict(chat),
            },
        )

    def _build_session_key(self, message: GatewayMessage) -> GatewaySessionKey:
        """Build a GatewaySessionKey from a gateway message.

        Telegram private chats use chat_id as the key.
        Group chats use group chat_id with optional thread_id.
        """
        chat_type = "private"
        thread_id = None
        meta = message.metadata or {}
        chat = meta.get("chat", {})

        # Detect chat type from Telegram metadata
        chat_type_from_meta = meta.get("chat_type", "")
        if chat_type_from_meta in ("group", "supergroup"):
            chat_type = "group"
        elif chat_type_from_meta == "channel":
            chat_type = "channel"

        # Thread support for groups
        if meta.get("is_topic_message"):
            thread_id = str(meta.get("message_thread_id", ""))

        return GatewaySessionKey(
            platform="telegram",
            chat_type=chat_type,
            chat_id=message.external_id,
            thread_id=thread_id,
        )

    async def _reply(self, external_id: str, text: str) -> None:
        await self.send_response(
            GatewayResponse(text=text or "Done.", platform="telegram", external_id=str(external_id))
        )

    async def _process_message(self, message: GatewayMessage) -> str | None:
        """The reply to a message, or None when it started a run that replies when done."""
        text = await self.handle(message)
        if text is None:
            return "Message blocked by safety check."

        meta = message.metadata or {}
        sender_id = str(meta.get("user_id") or message.external_id)
        if not self.is_authorized("telegram", message.external_id, sender_id):
            logger.warning(
                "Telegram message rejected by gateway allowlist: chat=%s user=%s",
                message.external_id,
                sender_id,
            )
            return (
                "🔒 This chat isn't authorized to use this bot yet.\n"
                "Ask the admin to run:\n"
                f"python -m cli.main gateway allowlist add --platform telegram --id {message.external_id}"
            )

        reply = await self.handle_ponytail_command(text)
        if reply is not None:
            return reply

        # Build session key from message metadata
        key = self._build_session_key(message)

        # Check for slash commands first
        if text.startswith("/"):
            cmd_response = self._command_dispatcher.dispatch(text)
            if cmd_response is not None:
                return await self._handle_command_response(cmd_response, key)

        if text.strip().lower() in ("new session", "start over"):
            return await self._handle_command_response("OK_NEW_SESSION", key)

        chat = key.composite_key()
        if chat in self._runs:
            return "⏳ Still working on your last message. Send /stop to cancel it."

        # Resolve or create session
        user_id = f"telegram-{message.external_id}"
        gw_session, flow_session_id = await self._flow_resolver.resolve(
            key=key,
            user_id=user_id,
            title=meta.get("chat_title") or meta.get("username"),
            metadata=meta,
        )

        # Build or reuse the Weebot session and flow
        session = await self._get_or_create_flow_session(flow_session_id, user_id)

        task = asyncio.create_task(self._run(session, text, message.external_id))
        self._runs[chat] = task
        task.add_done_callback(
            lambda t: self._runs.pop(chat, None) if self._runs.get(chat) is t else None
        )
        return None

    async def _run(self, session: Session, text: str, external_id: str) -> None:
        """Run the flow and send its last message; a cancel (/stop) still tears tools down."""
        response = ""
        try:
            async with run_scope(
                session, llm=self._llm, state_repo=self._state_repo, profile_name=self._profile_name
            ) as flow:
                async for event in flow.run(text):
                    if getattr(event, "type", "") == "message":
                        response = getattr(event, "message", "") or response
        except Exception as exc:
            logger.warning("Telegram run failed for session %s: %s", session.id, exc)
            return
        await self._reply(external_id, response or "(no response)")

    async def _stop_run(self, chat: str) -> bool:
        """Cancel the chat's run and wait for its teardown; False when none was running."""
        task = self._runs.pop(chat, None)
        if task is None:
            return False
        task.cancel()
        await asyncio.wait({task})  # not `await task`: that would re-raise its cancel here
        return True

    async def _get_or_create_flow_session(self, flow_session_id: str, user_id: str) -> Session:
        """Get or create a Weebot Session for the given flow session ID.

        Tries to load an existing session from the state repo first.
        If none exists, creates a fresh one.
        """

        try:
            existing = await self._state_repo.load_session(flow_session_id)
            if existing is not None:
                return existing
        except Exception:
            pass

        session = Session(id=flow_session_id, user_id=user_id, agent_id="telegram-agent")
        return session

    async def _handle_command_response(self, cmd_response: str, key: GatewaySessionKey) -> str:
        """Handle special command responses that require action beyond text.

        Commands like /new and /reset return special prefixes that instruct
        the adapter to perform actions.
        """
        if cmd_response == "OK_NEW_SESSION" or cmd_response == "OK_RESET_SESSION":
            await self._stop_run(key.composite_key())
            await self._flow_resolver.close(key)
            return "🔄 Session reset. Starting fresh."
        if cmd_response == "OK_STOP":
            if await self._stop_run(key.composite_key()):
                return "⏹ Task stopped."
            return "Nothing is running."
        if cmd_response.startswith("OK_SET_MODEL:"):
            model = cmd_response.split(":", 1)[1]
            return f"✅ Model set to: {model}"
        return cmd_response

    async def send_response(self, response: GatewayResponse) -> bool:
        if not response.success:
            return False

        chat_id = response.external_id

        # If the response has explicit media paths, use them
        if response.media_paths:
            return await self._send_telegram_media(chat_id, response)

        # Otherwise, extract media from the response text
        clean_text, media_paths, as_doc, as_voice = self.extract_media(response.text)
        if media_paths:
            response.text = clean_text
            response.media_paths = media_paths
            response.as_document = as_doc
            response.as_voice = as_voice
            return await self._send_telegram_media(chat_id, response)

        # Text-only fallback
        url = f"{self._api}/sendMessage"
        payload = {"chat_id": chat_id, "text": response.text[:4096]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    return resp.status == 200
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)
            return False

    async def _send_telegram_media(self, chat_id: str, response: GatewayResponse) -> bool:
        """Send media files natively using Telegram's sendPhoto/sendDocument/sendVoice."""
        import os as _os

        headers = {"Authorization": f"Bot {self._token}"}

        async with aiohttp.ClientSession(headers=headers) as session:
            for path in response.media_paths:
                ext = Path(path).suffix.lower()
                caption = response.text[:1024] if response.text else ""

                # Determine endpoint based on file type and directives
                if response.as_voice and ext in (".mp3", ".wav", ".ogg"):
                    endpoint = "sendVoice"
                elif response.as_document or ext in (".pdf", ".docx", ".xlsx", ".csv", ".json"):
                    endpoint = "sendDocument"
                elif ext in (".png", ".jpg", ".jpeg", ".gif", ".svg"):
                    endpoint = "sendPhoto"
                elif ext in (".mp4", ".webm"):
                    endpoint = "sendVideo"
                else:
                    endpoint = "sendDocument"

                url = f"{self._api}/{endpoint}"
                try:
                    async with aiohttp.ClientSession() as s:
                        data = aiohttp.FormData()
                        data.add_field("chat_id", chat_id)
                        data.add_field("caption", caption)
                        # Read up front: the old `with open` closed the file before the POST.
                        content = await asyncio.to_thread(Path(path).read_bytes)
                        data.add_field(
                            endpoint.replace("send", "").lower(),
                            content,
                            filename=_os.path.basename(path),
                        )
                        async with s.post(url, data=data) as resp:
                            if resp.status not in (200, 201):
                                error_body = await resp.text()
                                logger.warning(
                                    "Telegram media send failed (HTTP %d): %s",
                                    resp.status,
                                    error_body[:200],
                                )
                except Exception as exc:
                    logger.warning("Telegram media send failed: %s", exc)
                    return False

            return True
