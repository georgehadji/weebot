"""State repository port — abstract interface for session/task persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from weebot.domain.models.session import Session, SessionStatus


class StateRepositoryPort(ABC):
    """Abstract interface for persisting agent sessions and state."""

    @abstractmethod
    async def save_session(self, session: Session) -> None:
        """Persist a session."""
        ...

    async def save_session_if_unchanged(
        self, session: Session, expected_updated_at: datetime
    ) -> bool:
        """Save *session* only if the stored row's ``updated_at`` is still *expected_updated_at*.

        For a writer working from an old copy (the compaction job): False means someone saved
        in between and nothing was written. The default is load, compare, save, which another
        writer can race between the awaits; SQLiteStateRepository does it in one statement.
        """
        current = await self.load_session(session.id)
        if current is None or current.updated_at != expected_updated_at:
            return False
        await self.save_session(session)
        return True

    async def create_session(self, session: Session) -> bool:
        """Insert *session* only if its id is free; False when it already exists.

        The default is load-then-save, which another writer can race between the two
        awaits. SQLiteStateRepository serialises it; a multi-process store needs an
        atomic insert.
        """
        if await self.load_session(session.id) is not None:
            return False
        await self.save_session(session)
        return True

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

    async def count_sessions(self, user_id: str | None = None) -> int:
        """How many sessions *user_id* has (all users when None).

        A default over ``list_sessions`` so every repository answers it (W5.1);
        SQLiteStateRepository overrides it with a COUNT query.
        """
        total, offset, page = 0, 0, 500
        while True:
            batch = await self.list_sessions(user_id=user_id, limit=page, offset=offset)
            total += len(batch)
            if len(batch) < page:
                return total
            offset += page

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


async def all_sessions(
    repo: StateRepositoryPort,
    *,
    user_id: str | None = None,
    status: str | None = None,
    page: int = 500,
) -> list[Session]:
    """Every matching session, paged: ``list_sessions()`` alone returns the newest 100.

    A function, not a port method, so any object with ``list_sessions`` works.
    """
    sessions: list[Session] = []
    while True:
        batch = await repo.list_sessions(
            user_id=user_id, status=status, limit=page, offset=len(sessions)
        )
        sessions.extend(batch)
        if len(batch) < page:
            return sessions
