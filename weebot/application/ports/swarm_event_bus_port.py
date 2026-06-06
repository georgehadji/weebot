"""Swarm Event Bus port — inter-agent message routing via InterAgentMessage."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

from weebot.domain.models.inter_agent import InterAgentMessage

SwarmEventHandler = Callable[[InterAgentMessage], Awaitable[None]]


class SwarmEventBusPort(ABC):
    """Abstract interface for inter-agent message routing."""

    @abstractmethod
    async def publish(self, message: InterAgentMessage) -> None:
        """Publish an inter-agent message to all subscribers of its topic."""

    @abstractmethod
    async def subscribe(self, topic: str, handler: SwarmEventHandler) -> None:
        """Register a handler to receive messages on a topic."""

    @abstractmethod
    def get_history(self, topic: str) -> list[InterAgentMessage]:
        """Return all messages published on *topic* so far."""

    @abstractmethod
    def get_all_topics(self) -> list[str]:
        """Return all topics with messages."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
