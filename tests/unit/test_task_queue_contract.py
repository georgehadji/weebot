"""TaskQueuePort stays under one contract while nothing uses it (decision D4).

ADR-008 said the port was deleted; it was not, and it is kept on purpose for the Sep
plan's Phase 5.2 (scheduler extraction, multi-process dispatch). A reserved,
unused adapter rots, so both adapters run the same enqueue / dequeue / ack / close
sequence here. Redis is a small in-memory fake that implements only the stream
commands the adapter issues.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.domain.models.session import Session
from weebot.infrastructure.queue.in_memory_task_queue import InMemoryTaskQueue
from weebot.infrastructure.queue.redis_task_queue import RedisTaskQueue


class FakeRedis:
    """Streams, consumer group, XACK and XPENDING: the commands RedisTaskQueue issues."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self.delivered: dict[str, int] = {}
        self.pending: set[str] = set()
        self.groups: set[str] = set()

    async def xgroup_create(self, stream, group, id="0", mkstream=False):
        if (stream, group) in self.groups:
            raise RuntimeError("BUSYGROUP Consumer Group name already exists")
        self.groups.add((stream, group))
        self.streams.setdefault(stream, [])

    async def xadd(self, stream, data, maxlen=None):
        entries = self.streams.setdefault(stream, [])
        msg_id = f"{len(entries) + 1}-0"
        entries.append((msg_id, dict(data)))
        return msg_id

    async def xreadgroup(self, groupname, consumername, streams, count=1, block=0):
        (stream, _) = next(iter(streams.items()))
        entries = self.streams.get(stream, [])
        index = self.delivered.get(stream, 0)
        if index >= len(entries):
            await asyncio.sleep(0.01)
            return []
        self.delivered[stream] = index + 1
        msg_id, data = entries[index]
        self.pending.add(msg_id)
        return [(stream, [(msg_id, data)])]

    async def xack(self, stream, group, msg_id):
        self.pending.discard(msg_id)

    async def xpending(self, stream, group):
        return {"pending": len(self.pending)}

    async def aclose(self):
        return None


def _redis_queue() -> RedisTaskQueue:
    queue = RedisTaskQueue(redis_url="redis://fake")
    queue._redis = FakeRedis()
    return queue


@pytest.fixture(params=["in_memory", "redis"])
def queue(request):
    return InMemoryTaskQueue() if request.param == "in_memory" else _redis_queue()


def _session(sid: str) -> Session:
    return Session(id=sid, user_id="u", agent_id="a")


@pytest.mark.asyncio
async def test_an_enqueued_session_comes_back_with_its_factory(queue):
    def factory(session):  # noqa: ANN001
        return None

    await queue.enqueue(_session("s-1"), factory, priority=3)
    item = await asyncio.wait_for(queue.dequeue(), timeout=3)
    assert item is not None
    assert item.session.id == "s-1"
    assert item.flow_factory is factory
    assert item.priority == 3
    await queue.close()


@pytest.mark.asyncio
async def test_ack_is_idempotent(queue):
    await queue.enqueue(_session("s-2"), lambda s: None)
    item = await asyncio.wait_for(queue.dequeue(), timeout=3)
    await queue.ack(item)
    await queue.ack(item)  # a second ack must not raise
    await queue.close()


@pytest.mark.asyncio
async def test_length_is_a_non_negative_int(queue):
    """Meaning differs by backend: in-memory counts waiting items, Redis counts delivered
    but unacknowledged ones. Phase 5.2 must pick one before relying on it."""
    assert await queue.length() >= 0
    await queue.enqueue(_session("s-3"), lambda s: None)
    assert isinstance(await queue.length(), int)
    await queue.close()


@pytest.mark.asyncio
async def test_a_closed_queue_refuses_work_and_ends_dequeue(queue):
    await queue.close()
    with pytest.raises(RuntimeError):
        await queue.enqueue(_session("s-4"), lambda s: None)
    assert await asyncio.wait_for(queue.dequeue(), timeout=3) is None
