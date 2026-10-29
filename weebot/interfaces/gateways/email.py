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


from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.interfaces.gateways.base import (
    GatewayAdapter,
    GatewayMessage,
    GatewayResponse,
    flow_session_id,
)

logger = logging.getLogger(__name__)

# Senders never processed, even if allowlisted — replying to these risks an
# infinite autoresponder loop between weebot and another automated system.
_AUTOMATED_SENDER_MARKERS = ("mailer-daemon", "no-reply", "noreply", "postmaster")
_DKIM_PASS_DOMAIN = re.compile(r"dkim=pass[^;]*?header\.[di]=@?([\w.-]+)")
# Receiving servers whose Authentication-Results id is not their IMAP host.
_KNOWN_AUTHSERV_IDS: dict[str, tuple[str, ...]] = {"imap.gmail.com": ("mx.google.com",)}


def _trusted_ids_for(imap_server: str, configured: str | None) -> frozenset[str]:
    """The authserv-ids (RFC 8601) whose verdicts count: the setting, else the IMAP host's.

    ``EMAIL_TRUSTED_AUTHSERV_IDS`` (comma separated) wins. Without it: the IMAP host and
    any id its provider is known to stamp, such as Gmail's ``mx.google.com``.
    """
    if configured and configured.strip():
        return frozenset(i.strip().lower() for i in configured.split(",") if i.strip())
    host = imap_server.strip().lower()
    return frozenset({host, *_KNOWN_AUTHSERV_IDS.get(host, ())})


def _authserv_id(header: object) -> str:
    """The id before the first ``;`` (an optional version after it is ignored)."""
    head = str(header).split(";", 1)[0].split()
    return head[0].lower() if head else ""


def _sender_address(parsed) -> str:
    """The one address in ``From``, or "" when there is not exactly one.

    The first ``<...>`` in the header is not the sender: a display name can carry an
    allowlisted address ahead of the real one. Two ``From`` headers or two addresses
    are ambiguous, so the message gets no sender and is dropped.
    """
    addresses = email.utils.getaddresses(parsed.get_all("From", []))
    if len(addresses) != 1:
        return ""
    return addresses[0][1].strip()


def _sender_authenticated(parsed, sender: str, trusted_ids: frozenset[str]) -> bool:
    """True when the receiving server vouched for *sender*'s domain (F76).

    ``From`` alone is forgeable, and so is an ``Authentication-Results`` header: a
    sender can write its own, which is the topmost one when the receiving server adds
    none. Only the topmost header whose authserv-id is in *trusted_ids* counts (plan
    S5): DMARC pass for the domain, or a DKIM pass whose signing domain aligns.
    """
    domain = sender.rsplit("@", 1)[-1].strip().lower()
    results = parsed.get_all("Authentication-Results") or []
    ours = [str(h).lower() for h in results if _authserv_id(h) in trusted_ids]
    if results and not ours:
        logger.warning(
            "Authentication-Results from %s, none from a trusted server %s; "
            "set EMAIL_TRUSTED_AUTHSERV_IDS if this is your mail server",
            sorted({_authserv_id(h) for h in results}),
            sorted(trusted_ids),
        )
    if not domain or not ours:
        return False
    top = ours[0]
    if re.search(rf"dmarc=pass[^;]*header\.from={re.escape(domain)}\b", top):
        return True
    return any(d == domain or d.endswith("." + domain) for d in _DKIM_PASS_DOMAIN.findall(top))


class EmailAdapter(GatewayAdapter):
    """Adapter for email messaging via IMAP/SMTP."""

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        imap_server: str = "imap.gmail.com",
        imap_user: str | None = None,
        imap_password: str | None = None,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
        from_address: str | None = None,
        poll_interval_seconds: float = 30.0,
        profile_name: str | None = None,
        trusted_authserv_ids: str | None = None,
    ) -> None:
        super().__init__(llm_port=llm)
        self._imap_server = imap_server
        self._trusted_authserv_ids = _trusted_ids_for(imap_server, trusted_authserv_ids)
        self._imap_user = imap_user
        self._imap_password = imap_password
        self._smtp_server = smtp_server
        self._smtp_port = smtp_port
        self._from_address = from_address or imap_user
        self._state_repo = state_repo
        self._llm = llm
        self._poll_interval_seconds = poll_interval_seconds
        self._profile_name = profile_name
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("EmailAdapter started (account: %s)", self._imap_user)

    async def stop(self) -> None:
        self._running = False
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        logger.info("EmailAdapter stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                messages = await self.receive_messages()
                for msg in messages:
                    try:
                        text = await self._process_message(msg)
                        if text:
                            await self.send_response(
                                GatewayResponse(
                                    text=text, platform="email", external_id=msg.external_id
                                )
                            )
                    except Exception as exc:
                        logger.warning("Error processing email message: %s", exc)
            except Exception as exc:
                logger.error("Email poll error: %s", exc)
            await asyncio.sleep(self._poll_interval_seconds)

    async def _process_message(self, message: GatewayMessage) -> str:
        """Run an inbound email through PlanActFlow.

        Returns the response text, or ``""`` if the message was dropped
        (own address, automated sender, unauthorized sender, or safety
        block) — an empty return means no reply email is sent.
        """
        sender = message.external_id.strip().lower()

        # Anti-loop guards: never reply to ourselves or an automated
        # sender — email autoresponders can trigger infinite reply loops
        # between two bots, unlike chat platforms.
        if self._from_address and sender == self._from_address.strip().lower():
            return ""
        if any(marker in sender for marker in _AUTOMATED_SENDER_MARKERS):
            return ""

        if not self.is_authorized("email", sender):
            logger.warning("Email message rejected by gateway allowlist: from=%s", sender)
            return ""
        if not message.metadata.get("sender_authenticated"):
            # The allowlist matched a From header anyone can write (F76).
            logger.warning("Email rejected: mail server did not authenticate from=%s", sender)
            return ""

        text = await self.handle(message)
        if text is None:
            return "Message blocked by safety check."

        from weebot.domain.models.session import Session
        from weebot.interfaces.factories import run_scope

        session_id = flow_session_id("email", sender)
        session = Session(id=session_id, user_id=f"email-{sender}", agent_id="email-agent")

        response = ""
        async with run_scope(
            session, llm=self._llm, state_repo=self._state_repo, profile_name=self._profile_name
        ) as flow:
            async for event in flow.run(text):
                if getattr(event, "type", "") == "message":
                    response = getattr(event, "message", "") or response

        return response or "(no response produced)"

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
                                sender = _sender_address(parsed)
                                subject = parsed.get("Subject", "")
                                body = self._get_text_body(parsed)

                                if sender and body:
                                    result.append(
                                        GatewayMessage(
                                            platform="email",
                                            external_id=sender.strip(),
                                            text=body.strip()[:2000],
                                            metadata={
                                                "subject": subject,
                                                "message_id": parsed.get("Message-Id", ""),
                                                "in_reply_to": parsed.get("In-Reply-To", ""),
                                                "sender_authenticated": _sender_authenticated(
                                                    parsed,
                                                    sender.strip(),
                                                    self._trusted_authserv_ids,
                                                ),
                                            },
                                        )
                                    )
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
