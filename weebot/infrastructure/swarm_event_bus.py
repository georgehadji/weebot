"""SwarmEventBus — lightweight in-memory pub/sub for inter-agent messages.

Each swarm has one event bus instance.  Agents publish findings as they
discover them — the synthesizer subscribes to relevant topics and can
start forming clusters before all agents finish.

Usage:
    bus = SwarmEventBus()

    # In an agent:
    await bus.publish(InterAgentMessage(
        sender_agent_id="pricing_agent",
        topic="competitor_found",
        payload={"name": "Acme Corp", "pricing": "$199/mo"},
    ))

    # In the synthesizer:
    async for msg in bus.subscribe("competitor_found"):
        # Process findings as they arrive
        cluster.add(msg.payload)
"""
from __future__ import annotations

import asyncio
from typing import Optional

from weebot.domain.models.inter_agent import InterAgentMessage


class SwarmEventBus:
    """Per-swarm event bus for agent-to-agent messaging.

    Each topic maintains an asyncio.Queue so subscriber coroutines can
    iterate over messages as they arrive.  Messages are broadcast to all
    subscribers of that topic.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[InterAgentMessage]]] = {}
        self._history: dict[str, list[InterAgentMessage]] = {}

    async def publish(self, message: InterAgentMessage) -> None:
        """Broadcast *message* to all subscribers of its topic.

        The message is also appended to the topic history so late
        subscribers can catch up.
        """
        if message.topic not in self._queues:
            self._queues[message.topic] = []

        # Append to history (cap at 500 per topic)
        if message.topic not in self._history:
            self._history[message.topic] = []
        self._history[message.topic].append(message)
        if len(self._history[message.topic]) > 500:
            self._history[message.topic] = self._history[message.topic][-500:]

        # Deliver to all current subscribers
        for q in self._queues[message.topic]:
            await q.put(message)

    def subscribe(
        self,
        topic: str,
        replay_history: bool = True,
    ) -> "SwarmSubscription":
        """Return an async-iterable subscription to *topic*.

        Args:
            topic: Topic to subscribe to.
            replay_history: If True, yields past messages immediately.

        Returns:
            SwarmSubscription — use ``async for msg in sub: ...``.
        """
        queue: asyncio.Queue[InterAgentMessage] = asyncio.Queue()

        # Replay history for late subscribers
        if replay_history and topic in self._history:
            for msg in self._history[topic]:
                queue.put_nowait(msg)

        if topic not in self._queues:
            self._queues[topic] = []
        self._queues[topic].append(queue)

        return SwarmSubscription(queue, topic, self._unsubscribe)

    def _unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        if topic in self._queues:
            self._queues[topic] = [q for q in self._queues[topic] if q is not queue]

    def get_history(self, topic: str) -> list[InterAgentMessage]:
        """Return all messages published on *topic* so far."""
        return list(self._history.get(topic, []))

    def get_all_topics(self) -> list[str]:
        """Return all topics that have been published."""
        return list(self._history.keys())


class SwarmSubscription:
    """Async-iterable subscription to a SwarmEventBus topic.

    Yields messages as they arrive.  The subscription is closed when
    the context manager or async for loop exits.
    """

    def __init__(
        self,
        queue: asyncio.Queue[InterAgentMessage],
        topic: str,
        unsubscribe_fn,
    ) -> None:
        self._queue = queue
        self._topic = topic
        self._unsubscribe_fn = unsubscribe_fn
        self._closed = False

    def __aiter__(self) -> "SwarmSubscription":
        return self

    async def __anext__(self) -> InterAgentMessage:
        if self._closed:
            raise StopAsyncIteration
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=300.0)
        except asyncio.TimeoutError:
            self.close()
            raise StopAsyncIteration

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._unsubscribe_fn(self._topic, self._queue)

    async def __aenter__(self) -> "SwarmSubscription":
        return self

    async def __aexit__(self, *args) -> None:
        self.close()
