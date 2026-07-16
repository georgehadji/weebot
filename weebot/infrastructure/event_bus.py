"""Async event bus implementation — distributes events to all subscribers."""
from __future__ import annotations

import asyncio
import logging
from typing import List, TYPE_CHECKING

from weebot.application.ports.event_bus_port import (
    DomainEventHandler,
    EventBusPort,
    EventHandler,
)
from weebot.domain.models.event import AgentEvent, DomainEvent

if TYPE_CHECKING:
    from weebot.application.ports.event_store_port import EventStorePort

# Prometheus metrics — lazily imported to avoid circular import at module level
_metrics_cache = None
def _get_metrics():
    global _metrics_cache
    if _metrics_cache is None:
        from weebot.infrastructure.observability import metrics as _m
        _metrics_cache = _m
    return _metrics_cache


_metrics_reset_hook = None

def _reset_metrics_cache() -> None:
    """Reset the metrics cache.

    Used by test fixtures for clean isolation.
    """
    global _metrics_cache
    _metrics_cache = None

logger = logging.getLogger(__name__)


class AsyncEventBus(EventBusPort):
    """In-memory async event bus. Safe for single-process use.

    Args:
        handler_timeout: Maximum seconds each subscriber has to process an
            event (default 30). A timed-out handler is logged and the event
            continues to other subscribers. Set to 0 or None to disable.
    """

    def __init__(self, handler_timeout: float | None = 30.0) -> None:
        self._handler_timeout = handler_timeout
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

    async def _safe_call(self, handler: EventHandler, event: AgentEvent) -> None:
        timeout = self._handler_timeout
        if timeout is not None and timeout > 0:
            try:
                await asyncio.wait_for(handler(event), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Event handler %s timed out after %ss — event %s dropped for this subscriber",
                    getattr(handler, "__name__", handler), timeout,
                    getattr(event, "type", type(event).__name__),
                )
        else:
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

    async def _safe_call_domain(
        self, handler: DomainEventHandler, event: DomainEvent
    ) -> None:
        timeout = self._handler_timeout
        if timeout is not None and timeout > 0:
            try:
                await asyncio.wait_for(handler(event), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Domain handler %s timed out after %ss — event %s dropped",
                    getattr(handler, "__name__", handler), timeout,
                    getattr(event, "type", type(event).__name__),
                )
        else:
            await handler(event)

    def subscribe_domain(self, handler: DomainEventHandler) -> None:
        self._domain_handlers.append(handler)

    def unsubscribe_domain(self, handler: DomainEventHandler) -> None:
        if handler in self._domain_handlers:
            self._domain_handlers.remove(handler)


class DurableEventBus(EventBusPort):
    """EventBusPort decorator that journals events before fan-out.

    Wraps an inner ``AsyncEventBus`` and writes every event to an
    ``EventStorePort`` before delegating to ``publish()`` / ``publish_domain_event()``.

    Journal writes are fire-and-forget — a failed journal write is logged
    but never blocks event delivery.  This ensures durability without
    introducing a write-path dependency on the event store.

    Args:
        inner: The in-memory event bus that handles actual subscriber fan-out.
        event_store: The persistent event store for journalling.
    """

    def __init__(
        self,
        inner: AsyncEventBus,
        event_store: "EventStorePort",
    ) -> None:
        self._inner = inner
        self._event_store = event_store

    # ── Agent events ────────────────────────────────────────────────

    async def publish(self, event: AgentEvent) -> None:
        await self._journal_agent(event)
        await self._inner.publish(event)

    # ── Domain events ───────────────────────────────────────────────

    async def publish_domain_event(self, event: DomainEvent) -> None:
        await self._journal_domain(event)
        await self._inner.publish_domain_event(event)

    # ── Subscriber management (delegated) ───────────────────────────

    def subscribe(self, handler: EventHandler) -> None:
        self._inner.subscribe(handler)

    def subscribe_domain(self, handler: DomainEventHandler) -> None:
        self._inner.subscribe_domain(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._inner.unsubscribe(handler)

    def unsubscribe_domain(self, handler: DomainEventHandler) -> None:
        self._inner.unsubscribe_domain(handler)

    # ── Journalling helpers ─────────────────────────────────────────

    async def _journal_agent(self, event: AgentEvent) -> None:
        """Write an agent event to the event store (best-effort)."""
        try:
            session_id = getattr(event, "session_id", "")  # type: ignore[union-attr]
            if not session_id:
                session_id = getattr(event, "id", "")  # type: ignore[union-attr]
            event_type = getattr(event, "type", type(event).__name__)  # type: ignore[union-attr]
            data = event.model_dump() if hasattr(event, "model_dump") else {"raw": str(event)}  # type: ignore[union-attr]
            await self._event_store.log_event(
                session_id=str(session_id),
                event_type=str(event_type),
                data=data,
            )
        except Exception:
            logger.warning(
                "Journal write failed for event %s — event delivery continues",
                getattr(event, "type", type(event).__name__),
                exc_info=True,
            )

    async def _journal_domain(self, event: DomainEvent) -> None:
        """Write a domain event to the event store (best-effort)."""
        try:
            session_id = getattr(event, "session_id", "")
            event_type = getattr(event, "type", type(event).__name__)
            data = event.model_dump() if hasattr(event, "model_dump") else {"raw": str(event)}
            await self._event_store.log_event(
                session_id=str(session_id or ""),
                event_type=str(event_type),
                data=data,
            )
        except Exception:
            logger.warning(
                "Journal write failed for domain event %s — event delivery continues",
                getattr(event, "type", type(event).__name__),
                exc_info=True,
            )



