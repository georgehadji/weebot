"""Async event bus implementation — distributes events to all subscribers."""
from __future__ import annotations

import asyncio
import logging
from typing import List

from weebot.application.ports.event_bus_port import EventBusPort, EventHandler
from weebot.domain.models.event import AgentEvent

logger = logging.getLogger(__name__)


class AsyncEventBus(EventBusPort):
    """In-memory async event bus. Safe for single-process use."""

    def __init__(self) -> None:
        self._handlers: List[EventHandler] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: AgentEvent) -> None:
        async with self._lock:
            handlers = list(self._handlers)
        if not handlers:
            return
        results = await asyncio.gather(
            *[self._safe_call(h, event) for h in handlers],
            return_exceptions=True,
        )
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("Event handler %s failed: %s", handlers[idx], result)

    @staticmethod
    async def _safe_call(handler: EventHandler, event: AgentEvent) -> None:
        await handler(event)

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)


# Global singleton instance
_event_bus: AsyncEventBus | None = None


def get_event_bus() -> AsyncEventBus:
    """Get the global event bus singleton."""
    global _event_bus
    if _event_bus is None:
        _event_bus = AsyncEventBus()
    return _event_bus
