"""Valkey-backed event bus adapter with in-memory fallback (Redis-compatible).

Implements ``EventBusPort``.  When Valkey is unavailable (no ``WEEBOT_REDIS_URL``
env var or connection fails at first publish), falls back to ``AsyncEventBus``
so the system never breaks from a missing Valkey dependency.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from weebot.application.ports.event_bus_port import EventBusPort, EventHandler, DomainEventHandler
from weebot.domain.models.event import AgentEvent, DomainEvent

logger = logging.getLogger(__name__)

# Sentinel for unavailable Valkey
_VALKEY_UNAVAILABLE = object()


class ValkeyEventBus(EventBusPort):
    """Event bus backed by Valkey pub/sub, with in-memory fallback (Redis-compatible).

    Usage::

        bus = ValkeyEventBus(valkey_url="valkey://localhost:6379/0")
        bus.subscribe(my_handler)
        await bus.publish(event)

    When *redis_url* is ``None`` (default), reads ``WEEBOT_REDIS_URL`` from
    the environment.  If neither is set, falls back to in-memory event bus.
    """

    def __init__(self, valkey_url: Optional[str] = None):
        self._valkey_url = valkey_url
        self._redis: Any = None  # valkey client or _VALKEY_UNAVAILABLE
        self._in_memory: Any = None  # AsyncEventBus fallback
        self._lock = asyncio.Lock()
        self._subscribers: list[EventHandler] = []
        self._domain_subscribers: list[DomainEventHandler] = []

    # ── Lifecycle ─────────────────────────────────────────────────

    async def _ensure_valkey(self) -> Any:
        """Lazily connect to Valkey, falling back to in-memory on failure."""
        if self._redis is None:
            async with self._lock:
                if self._redis is not None:
                    return self._redis
                url = self._valkey_url
                if url is None:
                    try:
                        from weebot.config.secret_accessor import SecretAccessor
                        url = SecretAccessor.get("WEEBOT_VALKEY_URL") or SecretAccessor.get("WEEBOT_REDIS_URL")
                    except Exception:
                        url = None
                if url:
                    try:
                        import valkey.asyncio as aivalkey
                        self._redis = aivalkey.from_url(
                            url, decode_responses=True,
                            socket_connect_timeout=3,
                        )
                        await self._redis.ping()  # Valkey RESP-compatible
                        logger.info("ValkeyEventBus: connected to %s", url)
                        return self._redis
                    except Exception as exc:
                        logger.warning(
                            "ValkeyEventBus: cannot connect to %s (%s). "
                            "Falling back to in-memory bus.",
                            url, exc,
                        )
                # Fallback to in-memory
                self._redis = _VALKEY_UNAVAILABLE
                self._in_memory = self._create_in_memory()
                return self._redis
        return self._redis

    def _create_in_memory(self):
        """Create an in-memory AsyncEventBus instance as fallback."""
        from weebot.infrastructure.event_bus import AsyncEventBus
        bus = AsyncEventBus()
        for h in self._subscribers:
            bus.subscribe(h)
        for h in self._domain_subscribers:
            bus.subscribe_domain(h)
        return bus

    async def _get_bus(self) -> Any:
        """Return the active bus: Redis client or in-memory."""
        r = await self._ensure_valkey()
        if r is _VALKEY_UNAVAILABLE:
            return self._in_memory
        return r

    # ── EventBusPort implementation ──────────────────────────────

    async def publish(self, event: AgentEvent) -> None:
        """Publish an agent event."""
        r = await self._ensure_valkey()
        if r is _VALKEY_UNAVAILABLE:
            await self._in_memory.publish(event)
        else:
            # Valkey path: serialize to JSON and publish to channel
            try:
                payload = json.dumps(event.model_dump(mode="json"), default=str)
                await r.publish("weebot:events", payload)
            except Exception as exc:
                logger.error("ValkeyEventBus: publish failed: %s", exc)

    async def publish_domain_event(self, event: DomainEvent) -> None:
        """Publish a domain event."""
        r = await self._ensure_valkey()
        if r is _VALKEY_UNAVAILABLE:
            await self._in_memory.publish_domain_event(event)
        else:
            try:
                payload = json.dumps(event.model_dump(mode="json"), default=str)
                await r.publish("weebot:domain_events", payload)
            except Exception as exc:
                logger.error("ValkeyEventBus: domain publish failed: %s", exc)

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)
        if self._in_memory is not None:
            self._in_memory.subscribe(handler)

    def subscribe_domain(self, handler: DomainEventHandler) -> None:
        self._domain_subscribers.append(handler)
        if self._in_memory is not None:
            self._in_memory.subscribe_domain(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._subscribers = [h for h in self._subscribers if h is not handler]
        if self._in_memory is not None:
            self._in_memory.unsubscribe(handler)

    def unsubscribe_domain(self, handler: DomainEventHandler) -> None:
        self._domain_subscribers = [h for h in self._domain_subscribers if h is not handler]
        if self._in_memory is not None:
            self._in_memory.unsubscribe_domain(handler)


# Backward-compatible alias
RedisEventBus = ValkeyEventBus
