"""F24 repro: with Valkey connected, local subscribers receive nothing.

`ValkeyEventBus.publish` sends to the Valkey channel and nothing reads it
back, so in-process handlers are silently skipped. Decision 4 (fail fast)
satisfies this test by refusing to run; a bridge would satisfy it by
delivering. Fixed by W4.3 (refuse); see tasks/icm_fix_plan.md.
"""

from weebot.domain.models.event import MessageEvent
from weebot.infrastructure.events.redis_event_bus import ValkeyEventBus


class _ConnectedClient:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


async def test_publish_is_delivered_or_refused():
    bus = ValkeyEventBus(valkey_url="valkey://localhost:6379/0")
    bus._redis = _ConnectedClient()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(handler)
    try:
        await bus.publish(MessageEvent(message="hi"))
    except RuntimeError:
        return
    assert received, "event went to Valkey only; the local handler got nothing"
