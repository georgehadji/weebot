"""D4: the workflow orchestrator's events reach the event bus, scoped to a session.

EventBrokerAdapter had no caller. Wiring it needed three fixes first:
- `subscribe` called `subscribe_by_type`, which only AsyncEventBus has, so it
  raised on the DurableEventBus the container builds;
- an event without a session id became a NotificationEvent with an empty one,
  which the WebSocket broadcaster sends to every client; such events are now
  dropped instead;
- the orchestrator published without a session id, so it now stamps the session
  the tool runs in.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from weebot.domain.models.event import FactDiscovered, NotificationEvent
from weebot.infrastructure.events.broker_adapter import EventBrokerAdapter


class _PlainBus:
    """An EventBusPort without AsyncEventBus's subscribe_by_type."""

    def __init__(self):
        self.handlers = []
        self.published = []

    def subscribe(self, handler):
        self.handlers.append(handler)

    def unsubscribe(self, handler):
        self.handlers.remove(handler)

    async def publish(self, event):
        self.published.append(event)
        for h in list(self.handlers):
            await h(event)


async def test_subscribe_filters_by_type_on_any_bus():
    bus = _PlainBus()
    adapter = EventBrokerAdapter(bus)
    got = []

    async def handler(event):
        got.append(event)

    adapter.subscribe("fact_discovered", handler)
    await bus.publish(FactDiscovered(session_id="s1", key="k", value="v"))
    await bus.publish(NotificationEvent(session_id="s1", text="other"))
    assert [e.type for e in got] == ["fact_discovered"]


async def test_an_event_without_a_session_is_not_broadcast():
    bus = _PlainBus()
    adapter = EventBrokerAdapter(bus)
    assert await adapter.publish("workflow_started", "orch", {"task_count": 2}) is False
    assert bus.published == []
    assert await adapter.publish("workflow_started", "orch", {"session_id": "s1"}) is True
    assert bus.published[0].session_id == "s1"


async def test_the_orchestrator_stamps_its_session():
    from weebot.core.workflow_orchestrator import WorkflowOrchestrator

    publisher = SimpleNamespace(publish=AsyncMock(return_value=True))
    orchestrator = WorkflowOrchestrator(event_publisher=publisher, session_id="s1")
    await orchestrator._publish_event("workflow_started", {"task_count": 1}, orch_id="o1")
    data = publisher.publish.await_args.kwargs["data"]
    assert data == {"task_count": 1, "session_id": "s1"}


async def test_the_tool_hands_the_orchestrator_its_publisher_and_session(monkeypatch):
    from weebot.core.log_context import log_context
    from weebot.tools import workflow_orchestrator as module

    seen = {}

    class _Orchestrator:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def execute(self, graph):
            raise RuntimeError("stop here")

    monkeypatch.setattr(module, "WorkflowOrchestrator", _Orchestrator)
    publisher = object()
    tool = module.WorkflowOrchestratorTool(flow_factory=lambda s: None, event_publisher=publisher)
    with log_context(session_id="parent-1"):
        await tool.execute(tasks=[{"task_id": "a", "description": "p"}])
    assert seen["event_publisher"] is publisher and seen["session_id"] == "parent-1"


def test_the_registry_wires_the_publisher_into_the_tool():
    from pathlib import Path

    registry = Path("weebot/application/services/tool_registry.py").read_text(encoding="utf-8")
    factories = Path("weebot/application/di/_factories.py").read_text(encoding="utf-8")
    assert '"workflow_events"' in factories and "EventBrokerAdapter" in factories
    assert 'wired.get("workflow_events")' in registry
