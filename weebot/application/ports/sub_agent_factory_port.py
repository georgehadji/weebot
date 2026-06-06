"""Port for sub-agent lifecycle management."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.sub_agent import SubAgentResult, SubAgentSpec


class SubAgentFactoryPort(ABC):
    """Abstract interface for spawning and managing sub-agents."""

    @abstractmethod
    async def spawn(self, spec: SubAgentSpec) -> SubAgentResult:
        """Spawn a single sub-agent and return its result."""

    @abstractmethod
    async def spawn_parallel(
        self, specs: list[SubAgentSpec], max_concurrency: int = 4
    ) -> list[SubAgentResult]:
        """Spawn multiple sub-agents with concurrency control."""

    @abstractmethod
    async def spawn_voted(
        self, spec: SubAgentSpec, models: list[str] | None = None
    ) -> SubAgentResult:
        """Run the same spec on 2-3 models and return the consensus result."""
