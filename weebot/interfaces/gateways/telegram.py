"""TelegramAdapter — receive and respond to messages via Telegram Bot API.

Uses long-polling (getUpdates) to receive messages. Normalizes incoming
messages into GatewayMessage and routes responses back via sendMessage.

Requires TELEGRAM_BOT_TOKEN in .env.
"""
from __future__ import annotations

import asyncio
import logging
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


class TelegramAdapter(GatewayAdapter):
    """Bot API adapter for Telegram messaging."""

    def __init__(
        self,
        token: str,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        profile_name: str | None = None,
    ) -> None:
        super().__init__()
        self._token = token
        self._api = f"https://api.telegram.org/bot{token}"
        self._state_repo = state_repo
        self._llm = llm
        self._profile_name = profile_name
        self._offset = 0
        self._running = False

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
        logger.info("TelegramAdapter stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    msg = self._parse_update(update)
                    if msg:
                        try:
                            response_text = await self._process_message(msg)
                            await self.send_response(
                                GatewayResponse(
                                    text=response_text or "Done.",
                                    platform="telegram",
                                    external_id=str(msg.external_id),
                                )
                            )
                        except Exception as exc:
                            logger.warning("Error processing Telegram message: %s", exc)
            except Exception as exc:
                logger.error("Telegram poll error: %s", exc)
                await asyncio.sleep(5.0)

    async def _get_updates(self) -> list[dict]:
        url = f"{self._api}/getUpdates"
        params = {"offset": self._offset, "timeout": 30}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data.get("result", [])
        return []

    def _parse_update(self, update: dict) -> Optional[GatewayMessage]:
        msg = update.get("message", {})
        text = msg.get("text", "")
        chat = msg.get("chat", {})
        chat_id = chat.get("id", 0)

        self._offset = max(self._offset, update.get("update_id", 0) + 1)

        if not text or not chat_id:
            return None

        return GatewayMessage(
            platform="telegram",
            external_id=str(chat_id),
            text=text.strip(),
            metadata={
                "message_id": msg.get("message_id"),
                "username": chat.get("username", ""),
                "first_name": chat.get("first_name", ""),
            },
        )

    async def _process_message(self, message: GatewayMessage) -> str:
        text = await self.handle(message)
        if text is None:
            return "Message blocked by safety check."

        import uuid

        session_id = f"tg-{message.external_id}-{uuid.uuid4().hex[:6]}"
        from weebot.domain.models.session import Session

        session = Session(
            id=session_id,
            user_id=f"telegram-{message.external_id}",
            agent_id="telegram-agent",
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

        return response or "(no response)"

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
                if not _os.path.exists(path):
                    logger.warning("Media file not found: %s", path)
                    continue

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
                        data.add_field(endpoint.replace("send", "").lower(),
                                       open(path, "rb"),
                                       filename=_os.path.basename(path))
                        async with s.post(url, data=data) as resp:
                            if resp.status not in (200, 201):
                                error_body = await resp.text()
                                logger.warning(
                                    "Telegram media send failed (HTTP %d): %s",
                                    resp.status, error_body[:200],
                                )
                except Exception as exc:
                    logger.warning("Telegram media send failed: %s", exc)
                    return False

            return True
