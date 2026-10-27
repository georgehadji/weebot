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

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from weebot.application.ports.llm_port import LLMPort
from weebot.core.gateway_auth import GatewayAuth


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


class GatewayAdapter(ABC):
    """Base class for external platform adapters."""

    def __init__(self, llm_port: LLMPort) -> None:
        # Every adapter still receives `llm` from the entry point's container; nothing here
        # uses it since the inert safety gate went (A33), and the call sites stay as they are.
        self._auth = GatewayAuth()

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
