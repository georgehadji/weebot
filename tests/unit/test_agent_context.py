"""Tests for AgentContext and EventBroker."""

import asyncio
import pytest

from weebot.core.agent_context import AgentContext, EventBroker, ContextEvent
from weebot.activity_stream import ActivityStream


class TestEventBroker:
    """Test cases for EventBroker pub/sub."""

    def test_get_event_history(self):
        """Test retrieving event history."""
        broker = EventBroker()

        async def run():
            await broker.publish("event_a", "agent_1", {"type": "a"})
            await broker.publish("event_b", "agent_2", {"type": "b"})
            await broker.publish("event_a", "agent_3", {"type": "a"})

        asyncio.run(run())

        # Get all events
        all_events = broker.get_event_history()
        assert len(all_events) == 3

        # Get events of specific type
        type_a_events = broker.get_event_history("event_a")
        assert len(type_a_events) == 2
        assert all(e.event_type == "event_a" for e in type_a_events)

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self):
        """Test basic publish/subscribe functionality."""
        broker = EventBroker()
        received_events = []

        async def subscriber():
            try:
                async for event in broker.subscribe("test_event"):
                    received_events.append(event)
                    if len(received_events) >= 2:
                        break
            except asyncio.CancelledError:
                pass

        # Start subscriber task
        task = asyncio.create_task(subscriber())
        # Give subscriber time to register
        await asyncio.sleep(0.01)

        # Publish events
        await broker.publish("test_event", "agent_1", {"data": "value1"})
        await broker.publish("test_event", "agent_2", {"data": "value2"})

        # Wait for subscriber with timeout
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(received_events) == 2
        assert received_events[0].agent_id == "agent_1"
        assert received_events[1].agent_id == "agent_2"

    @pytest.mark.asyncio
    async def test_event_filtering_by_agent(self):
        """Test filtering events by agent_id."""
        broker = EventBroker()
        received_events = []

        async def subscriber():
            try:
                async for event in broker.subscribe("agent_event", agent_filter="agent_1"):
                    received_events.append(event)
                    if len(received_events) >= 1:
                        break
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)

        # Publish from different agents
        await broker.publish("agent_event", "agent_1", {})
        await broker.publish("agent_event", "agent_2", {})
        await broker.publish("agent_event", "agent_1", {})

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should only receive from agent_1
        assert len(received_events) == 1
        assert received_events[0].agent_id == "agent_1"


class TestAgentContext:
    """Test cases for AgentContext data and event sharing."""

    def test_create_orchestrator(self):
        """Test creating root orchestrator context."""
        context = AgentContext.create_orchestrator()

        assert context.nesting_level == 1
        assert context.parent_id is None
        assert context.orchestrator_id == context.agent_id
        assert context.shared_data == {}

    def test_create_child_context(self):
        """Test creating child context from orchestrator."""
        parent = AgentContext.create_orchestrator()
        child = AgentContext.create_child(parent, parent.agent_id, "researcher")

        assert child.nesting_level == 2
        assert child.parent_id == parent.agent_id
        assert child.orchestrator_id == parent.orchestrator_id
        assert child.shared_data is parent.shared_data  # Shared reference

    def test_nesting_level_validation(self):
        """Test nesting level validation."""
        # Orchestrator at level 1
        context = AgentContext.create_orchestrator()
        assert context.nesting_level == 1

        # Child at level 2
        child = AgentContext.create_child(context, context.agent_id, "analyst")
        assert child.nesting_level == 2

        # Grandchild at level 3
        grandchild = AgentContext.create_child(child, child.agent_id, "doc_writer")
        assert grandchild.nesting_level == 3

        # Cannot spawn great-grandchild
        with pytest.raises(RuntimeError) as exc_info:
            AgentContext.create_child(grandchild, grandchild.agent_id, "helper")
        assert "max nesting level" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_shared_data_and_result_storage(self):
        """Test storing and retrieving results through shared data."""
        context = AgentContext.create_orchestrator()

        # Store a result
        await context.store_result("researcher.findings", {"key": "value"})

        # Retrieve it
        result = await context.get_result("researcher.findings")
        assert result == {"key": "value"}

        # Test nested keys
        await context.store_result("analyst.metrics.accuracy", 0.95)
        assert await context.get_result("analyst.metrics.accuracy") == 0.95

        # Test missing key
        assert await context.get_result("nonexistent.key") is None

    @pytest.mark.asyncio
    async def test_event_publishing_from_context(self):
        """Test publishing events from context."""
        context = AgentContext.create_orchestrator()

        events = []

        async def listen():
            try:
                async for event in context.subscribe_to_events("test_event"):
                    events.append(event)
                    if len(events) >= 1:
                        break
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(listen())
        await asyncio.sleep(0.01)

        await context.publish_event("test_event", {"data": "test"})

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(events) == 1
        assert events[0].event_type == "test_event"
        assert events[0].agent_id == context.agent_id
