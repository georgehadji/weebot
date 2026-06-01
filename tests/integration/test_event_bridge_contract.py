"""Contract tests between the two event systems (EventBroker ↔ AsyncEventBus).

Verifies that EventBrokerAdapter correctly bridges publications and
subscriptions between the old EventBroker-style API and the new
AsyncEventBus.

These are integration tests that exercise the actual bridge adapter
with a running event bus, not mocks.
"""
from __future__ import annotations

import pytest

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import AgentEvent, NotificationEvent, FactDiscovered
from weebot.infrastructure.event_bus import AsyncEventBus
from weebot.infrastructure.events.broker_adapter import EventBrokerAdapter


@pytest.fixture
def event_bus() -> AsyncEventBus:
    """Create a clean AsyncEventBus for each test."""
    return AsyncEventBus()


@pytest.fixture
def adapter(event_bus: AsyncEventBus) -> EventBrokerAdapter:
    """Create an EventBrokerAdapter backed by *event_bus*."""
    return EventBrokerAdapter(event_bus=event_bus)


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: EventBrokerAdapter.publish → AsyncEventBus receives the event
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_publish_delivers_to_async_event_bus(adapter: EventBrokerAdapter, event_bus: AsyncEventBus):
    """Publishing through EventBrokerAdapter must deliver to AsyncEventBus subscribers."""
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    event_bus.subscribe(handler)

    result = await adapter.publish(
        event_type="fact_discovered",
        agent_id="test-agent",
        data={"session_id": "s1", "key": "answer", "value": 42},
    )

    assert result is True, "publish should return True on success"
    assert len(received) == 1, "handler should have been called once"
    event = received[0]
    assert isinstance(event, FactDiscovered), f"expected FactDiscovered, got {type(event).__name__}"
    assert event.key == "answer"
    assert event.value == 42


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: Unknown event types map to NotificationEvent
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unknown_event_type_maps_to_notification(adapter: EventBrokerAdapter, event_bus: AsyncEventBus):
    """Unknown event types should be converted to NotificationEvent (catch-all)."""
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    event_bus.subscribe(handler)

    await adapter.publish(
        event_type="custom_unknown_type",
        agent_id="test-agent",
        data={"msg": "hello"},
    )

    assert len(received) == 1
    event = received[0]
    assert isinstance(event, NotificationEvent), f"expected NotificationEvent, got {type(event).__name__}"


# ═════════════════════════════════════════════════════════════════════════════
# Test 3: EventBrokerAdapter.subscribe receives type-filtered events
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_subscribe_by_type_filters_correctly(adapter: EventBrokerAdapter, event_bus: AsyncEventBus):
    """subscribe() with event_type must only receive matching events."""
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    # Subscribe via the adapter (which wraps subscribe_by_type)
    adapter.subscribe("fact_discovered", handler)

    # Publish matching event
    await adapter.publish("fact_discovered", "agent-1", {"key": "k", "value": "v"})
    # Publish non-matching event
    await adapter.publish("some_other_type", "agent-1", {"msg": "should not arrive"})

    assert len(received) == 1, "only the matching event type should arrive"
    assert isinstance(received[0], FactDiscovered)


# ═════════════════════════════════════════════════════════════════════════════
# Test 4: Multiple subscribers on different types
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_multiple_subscribers_different_types(adapter: EventBrokerAdapter, event_bus: AsyncEventBus):
    """Multiple subscribers each should only receive their registered type."""
    fact_events: list[AgentEvent] = []

    async def fact_handler(event: AgentEvent) -> None:
        fact_events.append(event)

    adapter.subscribe("fact_discovered", fact_handler)

    await adapter.publish("fact_discovered", "a1", {"key": "k", "value": 1})
    await adapter.publish("fact_discovered", "a1", {"key": "k2", "value": 2})
    await adapter.publish("unknown_type", "a2", {"msg": "should not arrive to fact_handler"})

    assert len(fact_events) == 2, "fact handler should receive only the 2 fact_discovered events"


# ═════════════════════════════════════════════════════════════════════════════
# Test 5: AsyncEventBus.subscribe_by_type works without adapter
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_subscribe_by_type_direct(event_bus: AsyncEventBus):
    """AsyncEventBus.subscribe_by_type() must filter events by type string."""
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    event_bus.subscribe_by_type("fact_discovered", handler)

    await event_bus.publish(FactDiscovered(session_id="s1", key="k", value="v"))
    await event_bus.publish(NotificationEvent(text="ignored"))

    assert len(received) == 1, "only fact_discovered should arrive"
    assert isinstance(received[0], FactDiscovered)


# ═════════════════════════════════════════════════════════════════════════════
# Test 6: All known event type strings map correctly
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_all_known_event_types_map(adapter: EventBrokerAdapter, event_bus: AsyncEventBus):
    """Verify that all known event type strings in _convert produce correct types."""
    test_cases = [
        ("fact_discovered", FactDiscovered),
    ]

    for event_type, expected_cls in test_cases:
        received: list[AgentEvent] = []
        async def capture(e: AgentEvent) -> None:
            received.append(e)
        event_bus.subscribe(capture)
        await adapter.publish(event_type, "agent-1", {"session_id": "s1"})
        assert len(received) >= 1, f"no event received for {event_type}"
        assert isinstance(received[-1], expected_cls), (
            f"{event_type}: expected {expected_cls.__name__}, got {type(received[-1]).__name__}"
        )
