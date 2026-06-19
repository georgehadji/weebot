"""Event bus port — abstract interface for publishing and subscribing to events."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable, Union

from weebot.domain.models.event import AgentEvent, DomainEvent
from weebot.application.ports.event_publisher_port import EventPublisherPort


EventHandler = Callable[[AgentEvent], Awaitable[None]]
DomainEventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventBusPort(EventPublisherPort):
    """Full event bus interface: publishing + subscriber management.

    Extends ``EventPublisherPort`` with subscriber-management methods
    needed by ``AsyncEventBus``.  Components that only need to publish
    events should depend on ``EventPublisherPort`` instead.
    """

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
