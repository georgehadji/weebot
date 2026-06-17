"""Email Gateway — send and receive messages via IMAP/SMTP.

Uses IMAP for incoming (poll or IDLE) and SMTP for outgoing.
Maps email threads to GatewaySessionKey using Message-Id and In-Reply-To headers.

Configuration (in .env):
    EMAIL_IMAP_SERVER=imap.gmail.com
    EMAIL_IMAP_USER=user@gmail.com
    EMAIL_IMAP_PASSWORD=app-password
    EMAIL_SMTP_SERVER=smtp.gmail.com
    EMAIL_SMTP_PORT=587
    EMAIL_FROM=user@gmail.com
"""
from __future__ import annotations

import asyncio
import email
import logging
import re
from email.mime.text import MIMEText
from typing import Any

import aiohttp

from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
)

logger = logging.getLogger(__name__)


class EmailAdapter(GatewayAdapter):
    """Adapter for email messaging via IMAP/SMTP."""

    def __init__(
        self,
        imap_server: str = "imap.gmail.com",
        imap_user: str | None = None,
        imap_password: str | None = None,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
        from_address: str | None = None,
    ) -> None:
        super().__init__()
        self._imap_server = imap_server
        self._imap_user = imap_user
        self._imap_password = imap_password
        self._smtp_server = smtp_server
        self._smtp_port = smtp_port
        self._from_address = from_address or imap_user
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("EmailAdapter started (account: %s)", self._imap_user)

    async def stop(self) -> None:
        self._running = False
        logger.info("EmailAdapter stopped")

    async def send_response(self, response: GatewayResponse) -> bool:
        """Send an email response via SMTP."""
        if not response.success:
            return False

        try:
            msg = MIMEText(response.text)
            msg["Subject"] = "Re: Weebot"
            msg["From"] = self._from_address or ""
            msg["To"] = response.external_id

            # Use asyncio subprocess for SMTP (smtplib is blocking)
            import smtplib
            import ssl
            loop = asyncio.get_event_loop()

            def _send():
                tls_context = ssl.create_default_context()
                with smtplib.SMTP(self._smtp_server, self._smtp_port) as server:
                    server.starttls(context=tls_context)
                    if self._imap_user and self._imap_password:
                        server.login(self._imap_user, self._imap_password)
                    server.send_message(msg)

            await loop.run_in_executor(None, _send)
            return True
        except Exception as exc:
            logger.warning("Email send failed: %s", exc)
            return False

    async def receive_messages(self) -> list[GatewayMessage]:
        """Poll for new emails via IMAP.

        Returns list of new GatewayMessages.
        """
        messages: list[GatewayMessage] = []

        if not self._imap_user or not self._imap_password:
            return messages

        import imaplib
        loop = asyncio.get_event_loop()

        def _fetch():
            result: list[GatewayMessage] = []
            try:
                with imaplib.IMAP4_SSL(self._imap_server) as imap:
                    imap.login(self._imap_user, self._imap_password)
                    imap.select("INBOX")

                    # Search for unseen messages
                    _, data = imap.search(None, "UNSEEN")
                    for num in data[0].split() if data[0] else []:
                        _, msg_data = imap.fetch(num, "(RFC822)")
                        for response_part in msg_data:
                            if isinstance(response_part, tuple):
                                raw_email = response_part[1]
                                parsed = email.message_from_bytes(raw_email)
                                sender = parsed.get("From", "")
                                subject = parsed.get("Subject", "")
                                body = self._get_text_body(parsed)

                                # Extract email address from "Name <email>" format
                                email_match = re.search(r'<([^>]+)>', sender)
                                if email_match:
                                    sender = email_match.group(1)

                                if sender and body:
                                    result.append(GatewayMessage(
                                        platform="email",
                                        external_id=sender.strip(),
                                        text=body.strip()[:2000],
                                        metadata={
                                            "subject": subject,
                                            "message_id": parsed.get("Message-Id", ""),
                                            "in_reply_to": parsed.get("In-Reply-To", ""),
                                        },
                                    ))
            except Exception as exc:
                logger.debug("Email fetch error: %s", exc)
            return result

        return await loop.run_in_executor(None, _fetch)

    @staticmethod
    def _get_text_body(parsed: email.message.Message) -> str:
        """Extract text body from an email message."""
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", errors="ignore")
        else:
            payload = parsed.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="ignore")
        return ""
