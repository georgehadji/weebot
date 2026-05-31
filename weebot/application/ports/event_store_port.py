"""Event store port — abstract interface for storing and querying events.

Provides an abstraction over the SQLite EventStore so that the trajectory
pipeline can be tested with an in-memory store.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from weebot.domain.models.trajectory import TrajectorySummary


class EventStorePort(ABC):
    """Abstract interface for event persistence."""

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
    async def save_trajectory(self, trajectory: TrajectorySummary) -> None:
        """Persist a scored trajectory for skill optimization."""
        ...

    @abstractmethod
    async def get_trajectories_by_skill(
        self,
        skill_name: str,
        skill_version: int,
        limit: int = 200,
    ) -> list[TrajectorySummary]:
        """Retrieve trajectories for a specific skill version."""
        ...

    @abstractmethod
    async def get_trajectories_by_session(
        self,
        session_id: str,
    ) -> list[TrajectorySummary]:
        """Retrieve all trajectories for a session."""
        ...
