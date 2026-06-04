"""Base gateway — abstract interface for external messaging adapters.

Gateways allow Weebot to receive and respond to messages from external
platforms (Telegram, Slack, SMS, etc.).  Each GatewayAdapter implements
the same lifecycle:

1. start() — initialize connections, register webhooks
2. handle_message(message) → process and route to PlanActFlow
3. send_response(response) → send back to the platform
4. stop() — clean up connections

All incoming messages pass through the SafetyChecker before execution.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from weebot.core.safety import SafetyChecker


@dataclass
class GatewayMessage:
    """A normalized message from any external platform."""
    platform: str                          # "telegram", "slack", "webhook"
    external_id: str                       # Platform-specific user/chat ID
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
    error: Optional[str] = None
    media_paths: list[str] = field(default_factory=list)
    as_document: bool = False
    as_voice: bool = False


_MEDIA_PATH_RE = re.compile(r'(?<!\w)(/[^\s;|<>{}`\']{10,})(?!\w)')
_AUDIO_VOICE_DIRECTIVE = "[[audio_as_voice]]"
_DOCUMENT_DIRECTIVE = "[[as_document]]"


class GatewayAdapter(ABC):
    """Base class for external platform adapters."""

    def __init__(self) -> None:
        self._safety = SafetyChecker()

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

    async def handle(self, message: GatewayMessage) -> Optional[str]:
        """Route an incoming message through safety checks.

        Returns the response text, or None if blocked by safety.
        """
        if self._safety.is_critical_operation(message.text, "gateway"):
            return None  # Blocked by safety
        return message.text

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
        import re

        as_voice = _AUDIO_VOICE_DIRECTIVE in text
        as_doc = _DOCUMENT_DIRECTIVE in text

        # Strip directives from text
        text = text.replace(_AUDIO_VOICE_DIRECTIVE, "").replace(_DOCUMENT_DIRECTIVE, "").strip()

        # Find bare absolute file paths
        paths = _MEDIA_PATH_RE.findall(text)
        # Filter out paths that definitely aren't media files
        media_extensions = {".png", ".jpg", ".jpeg", ".gif", ".svg",
                            ".mp4", ".mp3", ".wav", ".ogg", ".webm",
                            ".pdf", ".docx", ".xlsx", ".csv", ".json",
                            ".yaml", ".yml", ".md", ".txt"}

        valid_paths = []
        for p in paths:
            ext = Path(p).suffix.lower()
            if ext in media_extensions:
                valid_paths.append(p)
                text = text.replace(p, "")

        # Strip empty lines left behind
        text = "\n".join(line for line in text.split("\n") if line.strip())

        return text.strip(), valid_paths, as_doc, as_voice
