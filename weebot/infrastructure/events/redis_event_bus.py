"""ValkeyEventBus — share bus events between processes through Valkey pub/sub.

Selected with ``WEEBOT_EVENT_BUS=valkey`` (DI wraps it in DurableEventBus, so
the journal still sees every event this process publishes).

- ``publish`` delivers to this process's subscribers first, then sends the
  event on the channel tagged with this bus's origin id. A Valkey outage costs
  only the cross-process copy: local delivery never waits on it.
- A reader task receives the channel, drops messages carrying its own origin
  (no echo), rebuilds the event (``event_codec``) and delivers it locally. Remote
  events are not journaled again: the process that published them already did.
- The reader reconnects with exponential backoff, capped at ``max_delay``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from weebot.application.ports.event_bus_port import DomainEventHandler, EventBusPort, EventHandler
from weebot.domain.models.event import AgentEvent, DomainEvent
from weebot.infrastructure.events import event_codec

logger = logging.getLogger(__name__)

CHANNEL = "weebot:events"


class ValkeyEventBus(EventBusPort):
    """Local fan-out plus a Valkey channel shared by every weebot process.

    Args:
        valkey_url: Connection URL (``redis://`` / ``valkey://``). Never logged.
        client_factory: Builds the async client; defaults to ``valkey.asyncio``.
        reconnect_delay: First wait after a lost connection, in seconds.
        max_delay: Longest wait between reconnect attempts.
    """

    def __init__(
        self,
        valkey_url: str,
        *,
        channel: str = CHANNEL,
        client_factory: Callable[[], Any] | None = None,
        reconnect_delay: float = 0.5,
        max_delay: float = 30.0,
    ) -> None:
        from weebot.infrastructure.event_bus import AsyncEventBus

        self._url = valkey_url
        self._channel = channel
        self._client_factory = client_factory or self._default_client
        self._reconnect_delay = reconnect_delay
        self._max_delay = max_delay
        self._origin = uuid.uuid4().hex
        self._local = AsyncEventBus()
        self._client: Any = None
        self._reader: asyncio.Task | None = None

    def _default_client(self) -> Any:
        import valkey.asyncio as aivalkey

        return aivalkey.from_url(self._url, decode_responses=True, socket_connect_timeout=3)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the reader. Idempotent; publish() calls it too."""
        if self._reader is None or self._reader.done():
            self._reader = asyncio.create_task(self._read_forever(), name="valkey-event-reader")
            await asyncio.sleep(0)  # let it subscribe before the first publish

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                logger.debug("Valkey reader stopped", exc_info=True)
            self._reader = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.debug("Valkey client close failed", exc_info=True)
            self._client = None

    async def _connected(self) -> Any:
        if self._client is None:
            client = self._client_factory()
            await client.ping()
            self._client = client
        return self._client

    async def _read_forever(self) -> None:
        delay = self._reconnect_delay
        while True:
            pubsub = None
            try:
                client = await self._connected()
                pubsub = client.pubsub()
                await pubsub.subscribe(self._channel)
                delay = self._reconnect_delay
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message.get("type") == "message":
                        await self._deliver_remote(message.get("data", ""))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Valkey event reader lost its connection (%s); retrying", exc)
                self._client = None
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_delay)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        logger.debug("Valkey pubsub close failed", exc_info=True)

    async def _deliver_remote(self, message: str) -> None:
        origin, event = event_codec.loads(message)
        if origin == self._origin or event is None:
            return
        if isinstance(event, DomainEvent):
            await self._local.publish_domain_event(event)
        else:
            await self._local.publish(event)

    async def _broadcast(self, event: Any) -> None:
        try:
            await self.start()
            client = await self._connected()
            await client.publish(self._channel, event_codec.dumps(self._origin, event))
        except Exception as exc:
            # Local subscribers already have it; only other processes miss this one.
            logger.warning("Valkey publish failed (%s); delivered locally only", exc)

    # ── EventBusPort ──────────────────────────────────────────────

    async def publish(self, event: AgentEvent) -> None:
        await self._local.publish(event)
        await self._broadcast(event)

    async def publish_domain_event(self, event: DomainEvent) -> None:
        await self._local.publish_domain_event(event)
        await self._broadcast(event)

    def subscribe(self, handler: EventHandler) -> None:
        self._local.subscribe(handler)

    def subscribe_domain(self, handler: DomainEventHandler) -> None:
        self._local.subscribe_domain(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._local.unsubscribe(handler)

    def unsubscribe_domain(self, handler: DomainEventHandler) -> None:
        self._local.unsubscribe_domain(handler)


# Backward-compatible alias
RedisEventBus = ValkeyEventBus
