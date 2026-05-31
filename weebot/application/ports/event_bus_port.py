"""Event bus port — abstract interface for publishing and subscribing to events."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from weebot.domain.models.event import AgentEvent


EventHandler = Callable[[AgentEvent], Awaitable[None]]


class EventBusPort(ABC):
    """Abstract interface for async event distribution."""

    @abstractmethod
    async def publish(self, event: AgentEvent) -> None:
        """Publish an event to all subscribers."""
        ...

    @abstractmethod
    def subscribe(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        ...

    @abstractmethod
    def unsubscribe(self, handler: EventHandler) -> None:
        """Unsubscribe a handler."""
        ...
