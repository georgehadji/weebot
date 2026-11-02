"""Token estimation for context-aware model selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from weebot.config.constants import IMAGE_PART_TOKENS

if TYPE_CHECKING:
    from weebot.domain.models.session import Session
    from weebot.domain.models.event import AgentEvent


class ContextTokenizer:
    """Estimates token count for sessions and events.

    Uses simple heuristics (4 chars ≈ 1 token) for estimation.
    More accurate than counting characters but faster than real tokenization.
    """

    # Token ratios by content type.
    # Single source of truth: weebot/config/constants.py
    from weebot.config.constants import CHARS_PER_TOKEN, CODE_CHARS_PER_TOKEN

    def estimate_session_tokens(self, session: Session) -> int:
        """Estimate total tokens in a session.

        Args:
            session: The session to estimate.

        Returns:
            Estimated token count.
        """
        total = 0
        for event in session.events:
            total += self.estimate_event_tokens(event)
        return total

    def estimate_event_tokens(self, event: AgentEvent) -> int:
        """Estimate tokens for a single event.

        Args:
            event: The event to estimate.

        Returns:
            Estimated token count.
        """
        try:
            text = str(event)
        except (MemoryError, RecursionError):
            # str(event) on pydantic models can blow up if a field
            # contains a very large object (e.g. a huge nested dict).
            # Fall back to a minimal estimate based on event type name.
            text = type(event).__name__
        # Rough estimation: characters / 4
        return len(text) // self.CHARS_PER_TOKEN

    def estimate_text_tokens(self, text: str, is_code: bool = False) -> int:
        """Estimate tokens for arbitrary text.

        Args:
            text: The text to estimate.
            is_code: Whether the text is code (more token-efficient).

        Returns:
            Estimated token count.
        """
        ratio = self.CODE_CHARS_PER_TOKEN if is_code else self.CHARS_PER_TOKEN
        return len(text) // ratio

    def estimate_remaining_context(self, session: Session, max_tokens: int = 128000) -> int:
        """Estimate remaining available context window.

        Args:
            session: The session to check.
            max_tokens: Maximum context window size.

        Returns:
            Remaining available tokens (>= 0).
        """
        used = self.estimate_session_tokens(session)
        return max(0, max_tokens - used)

    def estimate_messages_tokens(self, messages: list[dict]) -> int:
        """Estimate tokens for a list of chat messages.

        Args:
            messages: List of message dicts with 'content' key.

        Returns:
            Estimated token count.
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.estimate_text_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    total += self._estimate_part_tokens(part)
        return total

    def _estimate_part_tokens(self, part: Any) -> int:
        """Text by length, an image as a flat figure, any other block by its repr.

        An image's base64 is not text, and counting it as text made one screenshot look
        like 100k tokens (audit F15). A non-text block such as a tool result still counts,
        so compaction is not delayed by blocks that were never measured.
        """
        if not isinstance(part, dict):
            return self.estimate_text_tokens(str(part))
        if part.get("type") in ("image", "image_url") or "image_url" in part:
            return IMAGE_PART_TOKENS
        if isinstance(part.get("text"), str):
            return self.estimate_text_tokens(part["text"])
        return self.estimate_text_tokens(str(part))

    def is_long_context(self, session: Session, threshold: int = 50000) -> bool:
        """Check if session exceeds long context threshold.

        Args:
            session: The session to check.
            threshold: Token threshold for "long context".

        Returns:
            True if estimated tokens exceed threshold.
        """
        return self.estimate_session_tokens(session) > threshold
