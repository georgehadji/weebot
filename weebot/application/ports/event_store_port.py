"""Event store port — abstract interface for storing and querying events.

Provides an abstraction over the SQLite EventStore so that session event
logging can be tested with an in-memory store.  Trajectory-related methods
belong in the TrajectoryRepository, not here — this port covers raw event
persistence only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
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
        self,
        session_id: str,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all events for a session, optionally filtered by type."""
        ...

    @abstractmethod
    async def get_cost_summary(self, session_id: str) -> dict[str, Any]:
        """Get cost summary for a session."""
        ...
