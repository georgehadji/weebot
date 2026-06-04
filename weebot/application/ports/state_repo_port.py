"""State repository port — abstract interface for session/task persistence."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

from weebot.domain.models.session import Session, SessionStatus


class StateRepositoryPort(ABC):
    """Abstract interface for persisting agent sessions and state."""

    @abstractmethod
    async def save_session(self, session: Session) -> None:
        """Persist a session."""
        ...

    @abstractmethod
    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session by ID."""
        ...

    @abstractmethod
    async def list_sessions(self, user_id: Optional[str] = None) -> List[Session]:
        """List all sessions, optionally filtered by user."""
        ...

    @abstractmethod
    async def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        """Update just the status of a session."""
        ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        ...

    @abstractmethod
    async def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across all indexed sessions (M2).

        Args:
            query: Natural-language search query (porter-tokenized).
            limit: Maximum results.

        Returns:
            List of {session_id, event_type, summary, content, score}.
        """
        ...
