"""State repository port — abstract interface for session/task persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.session import Session, SessionStatus


class StateRepositoryPort(ABC):
    """Abstract interface for persisting agent sessions and state."""

    @abstractmethod
    async def save_session(self, session: Session) -> None:
        """Persist a session."""
        ...

    @abstractmethod
    async def load_session(self, session_id: str) -> Session | None:
        """Load a session by ID."""
        ...

    @abstractmethod
    async def list_sessions(
        self,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Session]:
        """List all sessions, optionally filtered by user, status, and paginated."""
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

    @abstractmethod
    async def get_low_salience_entries(self, threshold: float = 0.3, limit: int = 50) -> list[dict]:
        """Get memory entries below the salience threshold.

        Used for eviction candidates and user profile consolidation.

        Args:
            threshold: Maximum salience score to include (default 0.3).
            limit: Maximum results (default 50).

        Returns:
            List of dicts with keys ``entry_hash``, ``entry_text``, ``source``,
            ``salience``, ``access_count``, ``last_accessed``, ``created_at``.
        """
        ...
