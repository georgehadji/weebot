"""State repository port — abstract interface for session/task persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from weebot.domain.models.plan import StepStatus
from weebot.domain.models.session import Session, SessionStatus


@dataclass(frozen=True)
class SessionActivity:
    """What a session has done so far, for list views (audit R19).

    ``list_sessions`` leaves events unloaded to stay cheap, so list views read this
    instead of counting ``session.events``.
    """

    steps: int = 0
    steps_completed: int = 0
    tool_calls: int = 0
    messages: int = 0
    events: int = 0

    @classmethod
    def build(
        cls, counts: Mapping[tuple[str, str], int], plan_events: Sequence[Any]
    ) -> SessionActivity:
        """From event counts keyed by ``(type, status)`` and the plan and step events in order.

        Steps come from ``Session.get_last_plan``, so a list view and the session agree.
        """
        plan = Session(events=list(plan_events)).get_last_plan() if plan_events else None
        steps = plan.steps if plan else []
        return cls(
            steps=len(steps),
            steps_completed=sum(1 for s in steps if s.status == StepStatus.COMPLETED),
            tool_calls=counts.get(("tool", "calling"), 0),
            messages=sum(n for (kind, _), n in counts.items() if kind == "message"),
            events=sum(counts.values()),
        )

    @classmethod
    def of(cls, session: Session) -> SessionActivity:
        """The same answer from a loaded session's events."""

        def _status(event: Any) -> str:
            status = getattr(event, "status", "")
            return str(getattr(status, "value", status) or "")

        counts = Counter((e.type, _status(e)) for e in session.events)
        return cls.build(counts, [e for e in session.events if e.type in ("plan", "step")])


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

    async def count_sessions(self, user_id: str | None = None, status: str | None = None) -> int:
        """How many sessions *user_id* has (all users when None), optionally in *status*.

        A default over ``list_sessions`` so every repository answers it (W5.1);
        SQLiteStateRepository overrides it with a COUNT query.
        """
        total, offset, page = 0, 0, 500
        while True:
            batch = await self.list_sessions(
                user_id=user_id, status=status, limit=page, offset=offset
            )
            total += len(batch)
            if len(batch) < page:
                return total
            offset += page

    async def session_activity(self, session_ids: Sequence[str]) -> dict[str, SessionActivity]:
        """Activity per session id; a missing session reads as no activity (R19).

        A default that loads each session, for in-memory repositories; SQLite and
        PostgreSQL override it with grouped queries.
        """
        out: dict[str, SessionActivity] = {}
        for sid in session_ids:
            session = await self.load_session(sid)
            out[sid] = SessionActivity.of(session) if session else SessionActivity()
        return out

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
