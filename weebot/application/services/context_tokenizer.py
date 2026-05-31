"""Token estimation for context-aware model selection."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Dict

if TYPE_CHECKING:
    from weebot.domain.models.session import Session
    from weebot.domain.models.event import AgentEvent


class ContextTokenizer:
    """Estimates token count for sessions and events.
    
    Uses simple heuristics (4 chars ≈ 1 token) for estimation.
    More accurate than counting characters but faster than real tokenization.
    """
    
    # Token ratios by content type
    CHARS_PER_TOKEN = 4
    CODE_CHARS_PER_TOKEN = 3.5  # Code is more token-efficient
    
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
    
    def estimate_messages_tokens(self, messages: List[Dict]) -> int:
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
                # Handle multi-modal content
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total += self.estimate_text_tokens(part["text"])
        return total
    
    def is_long_context(self, session: Session, threshold: int = 50000) -> bool:
        """Check if session exceeds long context threshold.
        
        Args:
            session: The session to check.
            threshold: Token threshold for "long context".
            
        Returns:
            True if estimated tokens exceed threshold.
        """
        return self.estimate_session_tokens(session) > threshold
