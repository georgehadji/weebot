"""Event bus port — abstract interface for publishing and subscribing to events."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable, Union

from weebot.domain.models.event import AgentEvent, DomainEvent


EventHandler = Callable[[AgentEvent], Awaitable[None]]
DomainEventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventBusPort(ABC):
    """Abstract interface for async event distribution."""

    @abstractmethod
    async def publish(self, event: AgentEvent) -> None:
        """Publish an agent event to all subscribers."""
        ...

    @abstractmethod
    async def publish_domain_event(self, event: DomainEvent) -> None:
        """Publish an internal domain event to domain subscribers."""
        ...

    @abstractmethod
    def subscribe(self, handler: EventHandler) -> None:
        """Subscribe to all agent events."""
        ...

    @abstractmethod
    def subscribe_domain(self, handler: DomainEventHandler) -> None:
        """Subscribe to all domain events."""
        ...

    @abstractmethod
    def unsubscribe(self, handler: EventHandler) -> None:
        """Unsubscribe an agent event handler."""
        ...

    @abstractmethod
    def unsubscribe_domain(self, handler: DomainEventHandler) -> None:
        """Unsubscribe a domain event handler."""
        ...
