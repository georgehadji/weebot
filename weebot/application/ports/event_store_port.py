"""Event store port — abstract interface for storing and querying events.

Provides an abstraction over the SQLite EventStore so that session event
logging can be tested with an in-memory store.  Trajectory-related methods
belong in the TrajectoryRepository, not here — this port covers raw event
persistence only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any


class EventStorePort(ABC):
    """Abstract interface for event persistence (log, query, export)."""

    @abstractmethod
    async def log_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
        cost: float = 0.0,
        model: str = "",
        tokens_used: int = 0,
    ) -> int:
        """Persist an event."""
        ...

    @abstractmethod
    async def get_session_events(
        self, session_id: str, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all events for a session, optionally filtered by type."""
        ...

    @abstractmethod
    async def count_events(self, session_ids: Sequence[str]) -> dict[str, int]:
        """Number of stored events per session, in one query.

        Every id in *session_ids* is a key of the result (0 when it has no events), so a
        list page costs one call, never one per session.
        """
        ...

    @abstractmethod
    async def get_cost_summary(self, session_id: str) -> dict[str, Any]:
        """Get cost summary for a session."""
        ...

    @abstractmethod
    async def get_cost_window(self, window_hours: int) -> dict[str, Any]:
        """Sum the ``llm_call_completed`` events of the last *window_hours*.

        Returns ``{"total_cost", "total_tokens", "calls", "by_model": {model:
        {"cost", "tokens", "calls"}}}``. The one cost query (W4.2, F23).
        """
        ...

    @abstractmethod
    async def query_recent_events(
        self, event_type: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Query recent events across all sessions, optionally filtered by type.

        Used by DreamerAgent to collect recent failure signals for ideation.
        """
        ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session's events and its session record.

        Session-scoped purge, called by SessionDeletionOrchestrator when a
        session is deleted. DurableEventBus journals every agent event here,
        so without this a deleted session's full event history survives.
        Returns True if a session record was deleted.
        """
        ...
