"""TrajectoryRepositoryPort — abstract port for trajectory persistence.

Application layer defines the contract, infrastructure layer provides
the SQLite adapter (TrajectoryRepository).  Flows and CQRS handlers
depend on this port, not the concrete implementation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.failure_signature import FailureCluster, FailureSignature
from weebot.domain.models.trajectory import TrajectorySummary


class TrajectoryRepositoryPort(ABC):
    """Persistence port for trajectory evidence and failure signatures."""

    @abstractmethod
    async def save(self, trajectory: TrajectorySummary) -> None:
        """Persist a single trajectory."""

    @abstractmethod
    async def get_by_skill(
        self,
        skill_name: str,
        skill_version: int,
        limit: int = 200,
    ) -> list[TrajectorySummary]:
        """Retrieve trajectories for a specific skill version."""

    @abstractmethod
    async def get_by_session(
        self, session_id: str
    ) -> list[TrajectorySummary]:
        """Retrieve all trajectories for a session."""

    @abstractmethod
    async def save_failure_signature(self, signature: FailureSignature) -> None:
        """Persist a failure signature for clustering."""

    @abstractmethod
    async def get_clusters(
        self,
        min_support: int = 3,
        lookback_days: int = 7,
        max_clusters: int = 5,
        harness_version: str | None = None,
        model_id: str | None = None,
    ) -> list[FailureCluster]:
        """Group failure signatures into clusters."""

    @abstractmethod
    async def count_trajectories(self, lookback_days: int = 7) -> int:
        """Count total trajectories within the lookback window."""

    @abstractmethod
    async def get_sessions_without_signature(
        self,
        lookback_days: int = 7,
        max_sessions: int = 200,
        force_reprocess: bool = False,
    ) -> list[tuple[str, str | None, str | None, str | None]]:
        """Return (session_id, task_id, trajectory_text, failure_modes_json)
        for trajectories that lack a failure_signature entry."""
