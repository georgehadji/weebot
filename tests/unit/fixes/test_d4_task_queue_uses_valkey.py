"""D4 side fix: the durable task queue connects through `valkey`, which is pinned.

It imported `redis.asyncio`, which is not in the requirements, so
WEEBOT_QUEUE_BACKEND=redis failed with ImportError on the first task.
"""

import valkey.asyncio

from weebot.infrastructure.queue.redis_task_queue import RedisTaskQueue


async def test_the_queue_connects_with_the_valkey_client(monkeypatch):
    seen = {}

    def from_url(url, **kwargs):
        seen["url"] = url
        return "client"

    monkeypatch.setattr(valkey.asyncio, "from_url", from_url)
    queue = RedisTaskQueue(redis_url="redis://h:6379/0")
    assert await queue._get_redis() == "client"
    assert seen["url"] == "redis://h:6379/0"
