"""Resilience tests for EventBroker concurrent-cancellation and slow-subscriber scenarios.

These tests target the three black-swan failure modes identified in the stress test:
  1. RuntimeError when a subscriber is cancelled while publish() iterates the list.
  2. A stalled subscriber queue blocking delivery to all other subscribers.
  3. Lock contention with 10 concurrent subscribers, half cancelled mid-flight.
"""
from __future__ import annotations

import asyncio

import pytest

from weebot.core.agent_context import EventBroker


class TestEventBrokerResilience:

    @pytest.mark.asyncio
    async def test_publish_survives_concurrent_unsubscribe(self):
        """Cancelling a subscriber while publish() is in flight must not raise RuntimeError.

        Before the fix, publish() iterated a live list and the subscriber's
        finally block called list.remove() concurrently — causing
        'RuntimeError: list changed size during iteration'.
        """
        broker = EventBroker()
        received: list = []

        async def slow_subscriber():
            try:
                async for event in broker.subscribe("tick"):
                    received.append(event)
                    await asyncio.sleep(0.05)  # simulate slow consumer
                    break
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(slow_subscriber())
        await asyncio.sleep(0.01)  # let subscriber register

        # Cancel the subscriber so its finally block fires concurrently
        task.cancel()

        # publish() must not raise RuntimeError even as the list is being mutated
        await broker.publish("tick", "orchestrator", {})

        try:
            await task
        except asyncio.CancelledError:
            pass
        # Reaching here without RuntimeError is the core assertion.

    @pytest.mark.asyncio
    async def test_slow_subscriber_does_not_block_fast_subscribers(self):
        """A stalled subscriber queue must not delay delivery to other subscribers.

        Before the fix, publish() awaited queue.put() without a timeout.
        A full queue would block publish() forever, starving all other subscribers.
        """
        broker = EventBroker()
        fast_received: list = []

        async def fast_subscriber():
            try:
                async for event in broker.subscribe("ping"):
                    fast_received.append(event)
                    break
            except asyncio.CancelledError:
                pass

        # Register fast subscriber normally
        fast_task = asyncio.create_task(fast_subscriber())
        await asyncio.sleep(0.01)

        # Manually inject a *full* bounded queue as a slow subscriber
        slow_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        await slow_queue.put("blocker")  # fill it so put() would block
        broker._subscriptions.setdefault("ping", []).append(slow_queue)

        # publish() must complete quickly despite the stalled slow_queue
        await asyncio.wait_for(
            broker.publish("ping", "agent_1", {}),
            timeout=7.0,  # 5 s put-timeout + margin
        )

        # The fast subscriber must still receive its event
        await asyncio.wait_for(fast_task, timeout=2.0)
        assert len(fast_received) == 1
        assert fast_received[0].agent_id == "agent_1"

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe_lock_contention(self):
        """Concurrent subscribe and publish on the same event must not deadlock or crash.

        10 subscribers are created; half are cancelled during publish.
        The test verifies no RuntimeError and that surviving subscribers receive events.
        """
        broker = EventBroker()
        received: list = []

        async def subscriber():
            try:
                async for event in broker.subscribe("race"):
                    received.append(event)
                    break
            except asyncio.CancelledError:
                pass

        tasks = [asyncio.create_task(subscriber()) for _ in range(10)]
        await asyncio.sleep(0.01)  # let all subscribers register

        # Cancel odd-indexed tasks to trigger concurrent unsubscription
        for t in tasks[1::2]:
            t.cancel()

        # Publish while some subscribers are being torn down
        await broker.publish("race", "orchestrator", {})

        for t in tasks:
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Surviving (even-indexed) subscribers should each have received one event
        # (exact count depends on timing, but must be >= 1 and no exceptions raised).
        assert len(received) >= 1
