"""EventPublisherPort — minimal interface for publishing events.

Extracted from ``EventBusPort`` to follow Interface Segregation Principle.
``WebSocketEventBroadcaster`` only needs ``publish()`` — it should not be
forced to implement ``subscribe_domain()`` and other subscriber-management
methods that only ``AsyncEventBus`` uses.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.event import AgentEvent


class EventPublisherPort(ABC):
    """Minimal interface for publishing agent events.

    This is a narrower interface than ``EventBusPort`` — it covers only
    event publishing, not subscriber management.  Components that only
    need to emit events (WebSocket broadcasters, notification adapters)
    should depend on this port rather than the full ``EventBusPort``.
    """

    @abstractmethod
    async def publish(self, event: AgentEvent) -> None:
        """Publish an agent event to subscribers."""
        ...
