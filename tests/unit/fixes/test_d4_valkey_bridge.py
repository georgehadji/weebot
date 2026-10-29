"""D4: WEEBOT_EVENT_BUS=valkey shares events between processes through Valkey.

Before, ValkeyEventBus published to a channel nothing read back, so it refused to
publish when connected and DI refused any Valkey URL (W4.3, F24). The bridge now:
- delivers to this process's subscribers first, then publishes with an origin id;
- runs a reader that drops its own origin, rebuilds the event (four BaseEvent
  subclasses were missing from the AgentEvent union, and domain events had no
  type registry) and delivers it locally, without journaling it a second time;
- reconnects after a dropped connection;
- is chosen by WEEBOT_EVENT_BUS, not by a URL being set.

The fake broker below stands in for Valkey pub/sub; no fakeredis is installed.
"""

import asyncio
import importlib
import inspect

import pytest

from weebot.domain.models import event as events
from weebot.infrastructure.events.event_codec import decode, encode
from weebot.infrastructure.events.redis_event_bus import ValkeyEventBus


def _all_subclasses(cls):
    out = set()
    for sub in cls.__subclasses__():
        out.add(sub)
        out |= _all_subclasses(sub)
    return out


def test_every_agent_event_is_in_the_union():
    union = set(events.AgentEvent.__args__)
    concrete = {
        c for c in _all_subclasses(events.BaseEvent) if c.model_fields["type"].default
    }
    assert concrete <= union, sorted(c.__name__ for c in concrete - union)


@pytest.mark.parametrize(
    "event",
    [
        events.MessageEvent(session_id="s1", role="assistant", message="hi"),
        events.SessionStalenessEvent(session_id="s1"),
        events.FactDiscovered(session_id="s1", key="k", value=3),
        events.LLMCallCompleted(session_id="s1", model="m", cost=0.1),
    ],
)
def test_events_round_trip_with_their_session(event):
    back = decode(encode(event))
    assert type(back) is type(event)
    assert back.session_id == "s1"


def test_every_domain_event_type_can_be_rebuilt():
    for cls in _all_subclasses(events.DomainEvent):
        type_name = cls.model_fields["type"].default
        if not type_name or inspect.isabstract(cls):
            continue
        assert type_name in __import__(
            "weebot.infrastructure.events.event_codec", fromlist=["_DOMAIN_TYPES"]
        )._DOMAIN_TYPES, cls.__name__


class _Broker:
    def __init__(self):
        self.queues: list[asyncio.Queue] = []
        self.fail_next_read = False

    def client(self):
        return _Client(self)


class _PubSub:
    def __init__(self, broker):
        self._broker = broker
        self._queue: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, _channel):
        self._broker.queues.append(self._queue)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        if self._broker.fail_next_read:
            self._broker.fail_next_read = False
            raise ConnectionError("dropped")
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None

    async def aclose(self):
        if self._queue in self._broker.queues:
            self._broker.queues.remove(self._queue)


class _Client:
    def __init__(self, broker):
        self._broker = broker

    async def ping(self):
        return True

    async def publish(self, _channel, payload):
        for q in list(self._broker.queues):
            q.put_nowait({"type": "message", "data": payload})

    def pubsub(self):
        return _PubSub(self._broker)

    async def aclose(self):
        return None


async def _wait_for(predicate, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


async def test_two_processes_share_events_without_echo():
    broker = _Broker()
    a = ValkeyEventBus("valkey://x", client_factory=broker.client, reconnect_delay=0.01)
    b = ValkeyEventBus("valkey://x", client_factory=broker.client, reconnect_delay=0.01)
    got_a, got_b = [], []

    async def on_a(e):
        got_a.append(e)

    async def on_b(e):
        got_b.append(e)

    a.subscribe(on_a)
    b.subscribe(on_b)
    await a.start()
    await b.start()
    try:
        await a.publish(events.MessageEvent(session_id="s1", role="assistant", message="hi"))
        await _wait_for(lambda: got_b)
        await asyncio.sleep(0.05)
        assert len(got_a) == 1, "the publishing process saw its own event twice"
        assert got_b[0].message == "hi" and got_b[0].session_id == "s1"
    finally:
        await a.close()
        await b.close()


async def test_a_process_that_only_listens_still_hears_others():
    """Subscribing starts the reader: a listener never publishes, so nothing else would.

    Found by the live two-process run: a listen-only process got no events.
    """
    broker = _Broker()
    a = ValkeyEventBus("valkey://x", client_factory=broker.client, reconnect_delay=0.01)
    b = ValkeyEventBus("valkey://x", client_factory=broker.client, reconnect_delay=0.01)
    got_b = []

    async def on_b(e):
        got_b.append(e)

    b.subscribe(on_b)
    try:
        await _wait_for(lambda: len(broker.queues) >= 1)
        await a.publish(events.MessageEvent(session_id="s1", role="assistant", message="hi"))
        await _wait_for(lambda: got_b)
    finally:
        await a.close()
        await b.close()


async def test_the_reader_reconnects_after_a_dropped_connection():
    broker = _Broker()
    a = ValkeyEventBus("valkey://x", client_factory=broker.client, reconnect_delay=0.01)
    b = ValkeyEventBus("valkey://x", client_factory=broker.client, reconnect_delay=0.01)
    got_b = []

    async def on_b(e):
        got_b.append(e)

    b.subscribe(on_b)
    await b.start()
    broker.fail_next_read = True
    await asyncio.sleep(0.05)
    await a.start()
    try:
        await _wait_for(lambda: len(broker.queues) >= 2)
        await a.publish(events.MessageEvent(session_id="s1", role="assistant", message="again"))
        await _wait_for(lambda: got_b)
    finally:
        await a.close()
        await b.close()


class _LoopBoundClient(_Client):
    """Like the real client: it only works on the event loop that built it."""

    def __init__(self, broker):
        super().__init__(broker)
        self._loop = asyncio.get_running_loop()

    def _check(self):
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("attached to a different loop")

    async def ping(self):
        self._check()
        return True

    async def publish(self, channel, payload):
        self._check()
        await super().publish(channel, payload)


def test_a_second_event_loop_gets_a_fresh_client():
    """A second asyncio.run in one process must not publish through the dead loop's client."""
    broker = _Broker()
    a = ValkeyEventBus(
        "valkey://x", client_factory=lambda: _LoopBoundClient(broker), reconnect_delay=0.01
    )

    async def run_once(text):
        got = []
        b = ValkeyEventBus("valkey://x", client_factory=broker.client, reconnect_delay=0.01)

        async def on_b(e):
            got.append(e)

        b.subscribe(on_b)
        try:
            await _wait_for(lambda: len(broker.queues) >= 1)
            await a.publish(events.MessageEvent(session_id="s1", message=text))
            await _wait_for(lambda: got)
        finally:
            await b.close()
        return got[0].message

    assert asyncio.run(run_once("one")) == "one"
    assert asyncio.run(run_once("two")) == "two"


async def test_without_valkey_the_bus_still_delivers_locally():
    def unreachable():
        raise ConnectionError("no valkey")

    bus = ValkeyEventBus("valkey://x", client_factory=unreachable, reconnect_delay=0.01)
    got = []

    async def on(e):
        got.append(e)

    bus.subscribe(on)
    await bus.publish(events.MessageEvent(session_id="s1", message="local"))
    await bus.close()
    assert len(got) == 1


def test_the_flag_not_the_url_selects_valkey(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di import Container
    from weebot.config.secret_accessor import SecretAccessor
    from weebot.infrastructure.event_bus import AsyncEventBus, DurableEventBus

    monkeypatch.setattr(
        SecretAccessor,
        "get",
        staticmethod(lambda name, *a, **k: "valkey://h" if name == "WEEBOT_VALKEY_URL" else None),
    )
    container = Container()
    container.configure_defaults()

    monkeypatch.delenv("WEEBOT_EVENT_BUS", raising=False)
    importlib.reload(flags)
    bus = container._create_event_bus()
    assert isinstance(bus, DurableEventBus) and isinstance(bus._inner, AsyncEventBus)

    monkeypatch.setenv("WEEBOT_EVENT_BUS", "valkey")
    importlib.reload(flags)
    try:
        bus = container._create_event_bus()
        assert isinstance(bus._inner, ValkeyEventBus)
    finally:
        monkeypatch.delenv("WEEBOT_EVENT_BUS")
        importlib.reload(flags)


def test_valkey_without_a_url_fails_fast(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di import Container
    from weebot.config.secret_accessor import SecretAccessor

    monkeypatch.setattr(SecretAccessor, "get", staticmethod(lambda *a, **k: None))
    monkeypatch.setenv("WEEBOT_EVENT_BUS", "valkey")
    importlib.reload(flags)
    try:
        with pytest.raises(RuntimeError, match="WEEBOT_VALKEY_URL"):
            Container()._create_event_bus()
    finally:
        monkeypatch.delenv("WEEBOT_EVENT_BUS")
        importlib.reload(flags)
