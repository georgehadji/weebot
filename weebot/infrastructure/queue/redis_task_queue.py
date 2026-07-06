"""RedisTaskQueue — durable Redis Streams-backed session queue.

Requires ``WEEBOT_QUEUE_BACKEND=redis`` and a running Redis instance.

Uses Redis Streams with a consumer group so that:
  - Multiple workers can share the queue (multi-process deployment).
  - Messages are persisted — a worker crash does not lose the task.
  - Dead-letter stream captures permanently failed sessions.

Flow factories are Python callables and can't be serialised.  The queue
stores session IDs in Redis and maintains a local ``FactoryRegistry``
mapping session_id → factory.  In multi-process deployments each worker
must register factories independently.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Callable

from weebot.application.ports.task_queue_port import (
    TaskQueuePort,
    QueuedSession,
    FlowFactory,
)
from weebot.domain.models.session import Session

logger = logging.getLogger(__name__)

# Redis Stream keys
_STREAM_KEY = "weebot:task_queue"
_CONSUMER_GROUP = "weebot:workers"
_CONSUMER_ID = "worker"  # os.uname().nodename in production
_DEAD_LETTER_KEY = "weebot:task_queue:dead_letter"
_BLOCK_MS = 2000  # XREADGROUP block timeout


class FactoryRegistry:
    """In-memory mapping of session_id → FlowFactory.

    Shared across the process so that the Redis consumer can reconstruct
    ``QueuedSession`` objects when it dequeues a session ID.

    In single-process mode this is a simple dict.  In multi-process mode
    each worker must call ``register()`` with the same factories before
    processing starts.
    """

    def __init__(self) -> None:
        self._factories: dict[str, FlowFactory] = {}

    def register(self, session_id: str, factory: FlowFactory) -> None:
        self._factories[session_id] = factory

    def get(self, session_id: str) -> FlowFactory | None:
        return self._factories.get(session_id)

    def unregister(self, session_id: str) -> None:
        self._factories.pop(session_id, None)

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._factories


class RedisTaskQueue(TaskQueuePort):
    """Redis Streams-backed durable task queue.

    Args:
        redis_url: Redis connection URL (default from ``REDIS_URL`` env or
            ``redis://localhost:6379/0``).
        factory_registry: Optional shared registry; creates one if not provided.
        consumer_id: Unique consumer ID for the consumer group (default
            ``"worker"`` — override with hostname in multi-process mode).
    """

    def __init__(
        self,
        redis_url: str | None = None,
        factory_registry: FactoryRegistry | None = None,
        consumer_id: str | None = None,
    ) -> None:
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._consumer_id = consumer_id or os.getenv("HOSTNAME", _CONSUMER_ID)
        self._factories = factory_registry or FactoryRegistry()
        self._redis = None
        self._closed = False

    async def _get_redis(self):
        """Lazy-init the Redis connection."""
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
        return self._redis

    async def _ensure_group(self) -> None:
        """Create the stream and consumer group if they don't exist.

        ``MKSTREAM`` creates the stream on first write, and
        ``CREATE .. MKGROUP`` is idempotent (ignores BUSYGROUP error).
        """
        r = await self._get_redis()
        try:
            await r.xgroup_create(_STREAM_KEY, _CONSUMER_GROUP, id="0", mkstream=True)
        except Exception as exc:
            # BUSYGROUP: group already exists — expected on reconnects.
            if "BUSYGROUP" not in str(exc):
                logger.warning("Redis consumer group setup: %s", exc)

    async def enqueue(
        self,
        session: Session,
        flow_factory: FlowFactory,
        priority: int = 5,
    ) -> None:
        if self._closed:
            raise RuntimeError("TaskQueue is closed")

        r = await self._get_redis()
        await self._ensure_group()

        # Register the factory so the consumer can reconstruct the session
        self._factories.register(session.id, flow_factory)

        # Serialise session data + priority into the stream message
        data = {
            "session_id": session.id,
            "priority": str(priority),
            "status": session.status.value if session.status else "pending",
        }
        await r.xadd(_STREAM_KEY, data, maxlen=10_000)
        logger.debug("Enqueued session %s (priority=%d)", session.id, priority)

    async def dequeue(self) -> QueuedSession | None:
        r = await self._get_redis()
        await self._ensure_group()

        while not self._closed:
            try:
                result = await r.xreadgroup(
                    groupname=_CONSUMER_GROUP,
                    consumername=self._consumer_id,
                    streams={_STREAM_KEY: ">"},
                    count=1,
                    block=_BLOCK_MS,
                )
            except Exception as exc:
                logger.warning("Redis XREADGROUP failed: %s", exc)
                continue

            if not result:
                continue  # Timeout, loop again to check _closed

            # Parse the message
            stream_name, messages = result[0]
            msg_id, msg_data = messages[0]
            session_id = msg_data.get("session_id", "")
            priority = int(msg_data.get("priority", 5))

            # Look up the factory
            factory = self._factories.get(session_id)
            if factory is None:
                logger.warning(
                    "No factory registered for session %s — moving to dead-letter",
                    session_id,
                )
                await self._nack_to_dead_letter(msg_id, session_id, "no_factory")
                continue

            # Reconstruct the session from the state repo (already known to
            # the caller).  For the queued item we store a lightweight stub;
            # the consumer must reload from the state repo.
            stub_session = Session(
                id=session_id,
                user_id="",
                agent_id="",
            )

            item = QueuedSession(
                priority=priority,
                session=stub_session,
                flow_factory=factory,
            )
            # Store the Redis message ID so ack() can XACK it
            item._redis_msg_id = msg_id  # type: ignore[attr-defined]
            return item

        return None

    async def ack(self, item: QueuedSession) -> None:
        msg_id = getattr(item, "_redis_msg_id", None)
        if msg_id is None:
            return
        r = await self._get_redis()
        try:
            await r.xack(_STREAM_KEY, _CONSUMER_GROUP, msg_id)
        except Exception as exc:
            logger.warning("Redis XACK failed for msg %s: %s", msg_id, exc)

    async def length(self) -> int:
        r = await self._get_redis()
        try:
            info = await r.xpending(_STREAM_KEY, _CONSUMER_GROUP)
            return info.get("pending", 0) if isinstance(info, dict) else 0
        except Exception:
            return 0

    async def _nack_to_dead_letter(
        self, msg_id: str, session_id: str, reason: str
    ) -> None:
        """Move a message to the dead-letter stream and XACK it."""
        r = await self._get_redis()
        try:
            await r.xadd(
                _DEAD_LETTER_KEY,
                {"session_id": session_id, "reason": reason, "original_msg_id": msg_id},
                maxlen=5_000,
            )
            await r.xack(_STREAM_KEY, _CONSUMER_GROUP, msg_id)
        except Exception as exc:
            logger.warning("Dead-letter move failed for %s: %s", session_id, exc)

    async def close(self) -> None:
        self._closed = True
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None


__all__ = ["RedisTaskQueue", "FactoryRegistry"]
