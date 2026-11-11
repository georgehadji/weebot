"""Base gateway — abstract interface for external messaging adapters.

Gateways allow Weebot to receive and respond to messages from external
platforms (Telegram, Slack, SMS, etc.).  Each GatewayAdapter implements
the same lifecycle:

1. start() — initialize connections, register webhooks
2. handle_message(message) → process and route to PlanActFlow
3. send_response(response) → send back to the platform
4. stop() — clean up connections

Inbound text is not scanned for dangerous words: the actions a run can take are gated
by the guard chain on the tools (a word list refused ordinary sentences and, as written,
never fired: audit A33).
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from weebot.application.ports.llm_port import LLMPort
from weebot.core.gateway_auth import GatewayAuth
from weebot.domain.models.gateway_command import (
    CommandResult,
    Compress,
    ListTools,
    McpStatus,
    NewSession,
    Reply,
    ResumeSession,
    SetModel,
    StopRun,
)
from weebot.domain.models.gateway_session import GatewaySessionKey
from weebot.utils.backoff import BackoffConfig


class PollBackoff:
    """Capped exponential delay, with jitter, between failed polls (audit R10)."""

    def __init__(self, cap: float = 60.0, jitter: float = 0.25) -> None:
        self._delays = BackoffConfig(max_delay=cap).delays
        self._cap = cap
        self._jitter = jitter
        self._failures = 0

    def reset(self) -> None:
        self._failures = 0

    def next_delay(self, retry_after: float | None = None) -> float:
        """Seconds to wait before the next poll; the server's ``retry_after`` wins."""
        base = self._delays[min(self._failures, len(self._delays) - 1)]
        self._failures += 1
        if retry_after:
            return float(retry_after)
        return min(base * random.uniform(1 - self._jitter, 1 + self._jitter), self._cap)


_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def flow_session_id(platform: str, sender: str) -> str:
    """A Session id for one gateway run: platform, sender and a random suffix.

    Sender ids such as a Signal phone number (``+3069...``) or an email address carry
    characters Session ids reject, so those become ``_``; the sender part is cut to keep
    the id under Session's 128-character limit. The raw sender stays in ``user_id``.
    """
    safe = _UNSAFE_ID_CHARS.sub("_", sender)[:100]
    return f"{platform}-{safe}-{uuid.uuid4().hex[:6]}"


@dataclass
class GatewayMessage:
    """A normalized message from any external platform."""

    platform: str  # "telegram", "slack", "webhook"
    external_id: str  # Platform-specific user/chat ID
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class GatewayResponse:
    """A normalized response to an external platform."""

    text: str
    platform: str
    external_id: str
    success: bool = True
    error: str | None = None
    media_paths: list[str] = field(default_factory=list)
    as_document: bool = False
    as_voice: bool = False


_MEDIA_PATH_RE = re.compile(r"(?<!\w)(/[^\s;|<>{}`\']{10,})(?!\w)")
_AUDIO_VOICE_DIRECTIVE = "[[audio_as_voice]]"
_DOCUMENT_DIRECTIVE = "[[as_document]]"


@dataclass(frozen=True)
class ChannelCapabilities:
    """What a channel can do, so the base can adapt a reply to it (H28).

    ``max_len`` is the longest text one message carries (0: no limit). ``media`` names the kinds
    the adapter can send natively (``image``, ``document``, ``voice``, ``video``).
    """

    edit: bool = False
    typing: bool = False
    threads: bool = False
    max_len: int = 0
    media: frozenset[str] = frozenset()
    voice_in: bool = False


# The slash command each CommandResult comes from, for the "not available" reply.
_COMMAND_NAMES: dict[type, str] = {
    NewSession: "/new",
    StopRun: "/stop",
    SetModel: "/model set",
    ResumeSession: "/resume",
    ListTools: "/tools",
    McpStatus: "/mcp",
    Compress: "/compress",
}


class GatewayAdapter(ABC):
    """Base class for external platform adapters."""

    # The registry name (``telegram``) and what the channel can do. Subclasses set both.
    name: ClassVar[str] = ""
    capabilities: ClassVar[ChannelCapabilities] = ChannelCapabilities()

    @classmethod
    def configured(cls, settings: Any) -> bool:
        """Whether *settings* ask for this adapter to run (a token, an account, a mailbox)."""
        return False

    @classmethod
    def build(cls, settings: Any, container: Any) -> GatewayAdapter | None:
        """The adapter for a process that runs it from configuration, or None.

        Only long-running adapters (long polling) are built here; webhook adapters are built
        per request by their routers.
        """
        return None

    def __init__(self, llm_port: LLMPort) -> None:
        # Every adapter still receives `llm` from the entry point's container; nothing here
        # uses it since the inert safety gate went (A33), and the call sites stay as they are.
        self._auth = GatewayAuth()
        self._poll_task: asyncio.Task[None] | None = None

    def _start_polling(self, loop: Callable[[], Awaitable[None]]) -> bool:
        """Start *loop* as the poll task; False (and nothing started) while one still runs.

        A second ``start()`` used to start a second loop and orphan the first.
        """
        if self._poll_task is not None and not self._poll_task.done():
            return False
        self._poll_task = asyncio.create_task(loop())
        return True

    async def _stop_polling(self) -> None:
        """Cancel the poll task and wait for it; fine before ``start()`` and when called twice."""
        task, self._poll_task = self._poll_task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def is_authorized(self, platform: str, chat_id: str, user_id: str = "") -> bool:
        """Check an inbound chat/user against the gateway allowlist.

        Denies by default: a chat must be explicitly allowlisted (or
        ``allow_all_by_default`` set) via ``python -m cli.main gateway
        allowlist add``. Set ``WEEBOT_GATEWAY_AUTH_ENABLED=0`` to bypass
        entirely for trusted, non-public deployments.

        The chat-level allowlist is the primary gate (matches the single
        ``gateway allowlist add --platform X --id <chat_id>`` workflow). A
        per-user allowlist, if configured for the platform, adds a further
        restriction; an explicit user block always applies.
        """
        from weebot.config.settings import get_settings
        from weebot.domain.models.gateway_session import GatewaySessionKey

        if not get_settings().gateway_auth_enabled:
            return True
        if not self._auth.is_platform_allowed(platform):
            return False
        key = GatewaySessionKey(platform=platform, chat_type="private", chat_id=str(chat_id))
        if not self._auth.is_chat_allowed(key):
            return False

        config = self._auth.get_config()
        if user_id:
            user_id = str(user_id)
            if user_id in config.get("blocked_users", {}).get(platform, []):
                return False
            has_user_allowlist = bool(config.get("allowed_users", {}).get(platform))
            if has_user_allowlist and not self._auth.is_user_allowed(platform, user_id):
                return False
        return True

    @abstractmethod
    async def start(self) -> None:
        """Initialize connections and register webhooks/polling."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Clean up connections."""
        ...

    @abstractmethod
    async def send_response(self, response: GatewayResponse) -> bool:
        """Send a response back to the external platform."""
        ...

    # ── slash commands (typed results) ─────────────────────────────────────────

    def _command_handlers(
        self,
    ) -> dict[type, Callable[[Any, GatewaySessionKey], Awaitable[str]]]:
        """CommandResult type -> handler. A subclass extends this with what it can do."""
        return {Reply: self._cmd_reply}

    async def _cmd_reply(self, result: Reply, key: GatewaySessionKey) -> str:
        return result.text

    async def apply_command(self, result: CommandResult, key: GatewaySessionKey) -> str:
        """Do what a command asks and return the text to send back."""
        handler = self._command_handlers().get(type(result))
        if handler is None:
            command = _COMMAND_NAMES.get(type(result), "That command")
            return f"{command} is not available on {self.name or 'this channel'} yet."
        return await handler(result, key)

    def split_text(self, text: str) -> list[str]:
        """*text* in pieces of at most ``capabilities.max_len``, cut at a break or a space."""
        limit = self.capabilities.max_len
        if limit <= 0 or len(text) <= limit:
            return [text]
        pieces: list[str] = []
        rest = text
        while len(rest) > limit:
            cut = max(rest.rfind(sep, 0, limit) for sep in ("\n\n", "\n", " "))
            cut = cut if cut > 0 else limit
            pieces.append(rest[:cut].rstrip())
            rest = rest[cut:].lstrip()
        if rest:
            pieces.append(rest)
        return pieces

    async def handle(self, message: GatewayMessage) -> str | None:
        """The text to act on for an incoming message.

        Returns None only when a subclass refuses a message. Dangerous actions are not
        judged from the chat text: the tools the run uses are wrapped by the guard chain.
        """
        return message.text

    async def handle_ponytail_command(self, text: str) -> str | None:
        """Handle ``ponytail [mode]`` commands and return a reply, or None.

        Args:
            text: The incoming message text.

        Returns:
            Response text for the gateway to send back, or None if the text
            is not a Ponytail command.
        """
        is_command, mode = self.parse_ponytail_command(text)
        if not is_command:
            return None

        from cli.commands.ponytail import read_ponytail_mode, write_ponytail_mode

        if mode is None:
            return f"🐴 Ponytail mode is currently: {read_ponytail_mode()}"
        write_ponytail_mode(mode)
        return f"🐴 Ponytail mode set to: {mode}"

    @staticmethod
    def parse_ponytail_command(text: str) -> tuple[bool, str | None]:
        """Parse a Ponytail mode command from gateway message text.

        Supported forms:
        - ``ponytail``          → return current mode (reply mode is None)
        - ``ponytail off``      → set mode to off
        - ``ponytail lite``     → set mode to lite
        - ``ponytail full``     → set mode to full
        - ``ponytail ultra``    → set mode to ultra

        Returns:
            ``(is_command, mode_or_none)``. When *mode_or_none* is ``None``
            the caller should reply with the current mode.
        """
        from weebot.config.settings import PONYTAIL_MODES as allowed

        normalized = text.strip().lower()
        if normalized == "ponytail":
            return True, None
        if normalized.startswith("ponytail "):
            mode = normalized[len("ponytail ") :].strip()
            if mode in allowed:
                return True, mode
        return False, None

    @staticmethod
    def extract_media(text: str) -> tuple[str, list[str], bool, bool]:
        """Extract media file paths and directives from *text*.

        Scans for:
        - Bare absolute file paths (``/home/user/file.png``, ``C:\\path\\file.jpg``)
        - ``[[audio_as_voice]]`` directive → promote audio files to voice messages
        - ``[[as_document]]`` directive → deliver files as documents (no recompression)

        Args:
            text: Raw response text from the agent.

        Returns:
            Tuple of ``(cleaned_text, media_paths, as_document, as_voice)``.
            Directives are stripped from the returned text.
        """
        as_voice = _AUDIO_VOICE_DIRECTIVE in text
        as_doc = _DOCUMENT_DIRECTIVE in text

        # Strip directives from text
        text = text.replace(_AUDIO_VOICE_DIRECTIVE, "").replace(_DOCUMENT_DIRECTIVE, "").strip()

        # Find bare absolute file paths
        paths = _MEDIA_PATH_RE.findall(text)
        # Filter out paths that definitely aren't media files
        media_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".mp4",
            ".mp3",
            ".wav",
            ".ogg",
            ".webm",
            ".pdf",
            ".docx",
            ".xlsx",
            ".csv",
            ".json",
            ".yaml",
            ".yml",
            ".md",
            ".txt",
        }

        # Documents can hold secrets (a credentials .json named in a reply was
        # uploaded): attach them only from inside the project (F76).
        from weebot.core import output_path as _op

        document_extensions = {".pdf", ".docx", ".xlsx", ".csv", ".json", ".yaml", ".yml",
                               ".md", ".txt"}
        valid_paths = []
        for p in paths:
            ext = Path(p).suffix.lower()
            if ext in document_extensions and not Path(p).resolve().is_relative_to(
                _op._PROJECT_ROOT
            ):
                continue
            if ext in media_extensions:
                valid_paths.append(p)
                text = text.replace(p, "")

        # Strip empty lines left behind
        text = "\n".join(line for line in text.split("\n") if line.strip())

        return text.strip(), valid_paths, as_doc, as_voice
