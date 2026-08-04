"""SessionScopedEventBus — decorator that stamps a correlation id on publish.

Flows are handed one of these instead of the raw bus so that every
``AgentEvent`` they emit carries ``session_id`` without the flow itself
having to know or care about transport routing (WebSocket/SSE fan-out
keys on that field — see ``weebot.interfaces.web.event_broadcaster``).

Decorator, not a new port: this wraps an existing ``EventBusPort`` and
implements the exact same interface, so it is a drop-in substitute
anywhere a flow currently receives a bus.  Subscriber management
(``subscribe``/``subscribe_domain``/etc.) delegates straight through —
subscriptions are process-wide, not per-session.
"""
from __future__ import annotations

from weebot.application.ports.event_bus_port import (
    DomainEventHandler,
    EventBusPort,
    EventHandler,
)
from weebot.domain.models.event import AgentEvent, DomainEvent


class SessionScopedEventBus(EventBusPort):
    """Wraps an ``EventBusPort``, stamping ``session_id`` on every published event."""

    def __init__(self, inner: EventBusPort, session_id: str) -> None:
        self._inner = inner
        self._session_id = session_id

    async def publish(self, event: AgentEvent) -> None:
        """Stamp ``session_id`` (if not already set) and forward to the inner bus."""
        if not event.session_id:
            event = event.model_copy(update={"session_id": self._session_id})
        await self._inner.publish(event)

    async def publish_domain_event(self, event: DomainEvent) -> None:
        """Domain events are an internal concern, not wire transport — pass through unchanged."""
        await self._inner.publish_domain_event(event)

    def subscribe(self, handler: EventHandler) -> None:
        self._inner.subscribe(handler)

    def subscribe_domain(self, handler: DomainEventHandler) -> None:
        self._inner.subscribe_domain(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._inner.unsubscribe(handler)

    def unsubscribe_domain(self, handler: DomainEventHandler) -> None:
        self._inner.unsubscribe_domain(handler)
