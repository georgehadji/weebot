"""Async event bus implementation — distributes events to all subscribers."""
from __future__ import annotations

import asyncio
import logging
from typing import List

from weebot.application.ports.event_bus_port import (
    DomainEventHandler,
    EventBusPort,
    EventHandler,
)
from weebot.domain.models.event import AgentEvent, DomainEvent

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
        self._domain_handlers: List[DomainEventHandler] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: AgentEvent) -> None:
        # Prometheus counter
        try:
            _get_metrics().events_published_total.labels(
                event_type=getattr(event, "type", "unknown")
            ).inc()
        except Exception:
            logger.debug("Metrics increment failed — event delivery continues", exc_info=True)

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
                logger.exception("Event handler %s failed", handlers[idx])

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

    # ── Domain event support ────────────────────────────────────────

    async def publish_domain_event(self, event: DomainEvent) -> None:
        """Publish a domain event to all domain subscribers.

        Domain events are logged but use a separate subscriber list from
        agent events, so they don't interfere with SSE/UI event streams.
        """
        logger.debug(
            "Domain event: %s (session=%s)",
            getattr(event, "type", type(event).__name__),
            getattr(event, "session_id", "N/A"),
        )
        async with self._lock:
            handlers = list(self._domain_handlers)
        if not handlers:
            return
        results = await asyncio.gather(
            *[self._safe_call_domain(h, event) for h in handlers],
            return_exceptions=True,
        )
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "Domain handler %s failed: %s", handlers[idx], result
                )

    @staticmethod
    async def _safe_call_domain(
        handler: DomainEventHandler, event: DomainEvent
    ) -> None:
        await handler(event)

    def subscribe_domain(self, handler: DomainEventHandler) -> None:
        self._domain_handlers.append(handler)

    def unsubscribe_domain(self, handler: DomainEventHandler) -> None:
        if handler in self._domain_handlers:
            self._domain_handlers.remove(handler)



