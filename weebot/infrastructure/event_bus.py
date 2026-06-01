"""Async event bus implementation — distributes events to all subscribers."""
from __future__ import annotations

import asyncio
import logging
import warnings
from typing import List

from weebot.application.ports.event_bus_port import EventBusPort, EventHandler
from weebot.domain.models.event import AgentEvent

# Prometheus metrics — lazily imported to avoid circular import at module level
_metrics = None
def _get_metrics():
    global _metrics
    if _metrics is None:
        from weebot.infrastructure.observability import metrics as _m
        _metrics = _m
    return _metrics

logger = logging.getLogger(__name__)


class AsyncEventBus(EventBusPort):
    """In-memory async event bus. Safe for single-process use."""

    def __init__(self) -> None:
        self._handlers: List[EventHandler] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: AgentEvent) -> None:
        # Prometheus counter
        try:
            _get_metrics().events_published_total.labels(
                event_type=getattr(event, "type", "unknown")
            ).inc()
        except Exception:
            pass  # metrics must never break event delivery

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

    def subscribe_by_type(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to events matching a specific event type string.

        The handler is wrapped so it only fires when the event's type
        attribute matches *event_type* (exact match).  This mirrors the
        EventBroker.subscribe(event_type=…) semantics so that code using
        the old broker can migrate to AsyncEventBus easily.
        """
        from weebot.domain.models.event import AgentEvent

        async def filtered_handler(event: AgentEvent) -> None:
            # AgentEvent subclasses store the type in their 'type' field
            if getattr(event, "type", None) == event_type:
                await handler(event)

        self._handlers.append(filtered_handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)


# Global singleton instance
_event_bus: AsyncEventBus | None = None


def get_event_bus() -> AsyncEventBus:
    """Get the global event bus singleton.

    DEPRECATED: Use ``Container.get(EventBusPort)`` instead.
    See :class:`~weebot.application.di.Container` for the DI-based approach.
    Scheduled for removal by 2026-09-01.
    """
    warnings.warn(
        "get_event_bus() is deprecated. Use Container.get(EventBusPort) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    global _event_bus
    if _event_bus is None:
        _event_bus = AsyncEventBus()
    return _event_bus
