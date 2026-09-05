"""Wave 3 of the V7 defect hunt — flow state machine and subscription lifecycle.

Three defects, each proven by an executable trigger before the fix:

* An ``AsyncEventBus.subscribe_by_type`` subscription could never be cancelled.
  ``unsubscribe`` takes the caller's own handler reference and compares it
  against the list, but the list held a wrapper closure, so nothing matched.
  The subscription was permanent and the "unsubscribed" handler kept receiving
  every event -- a correctness bug, not only a leak. ``EventBrokerAdapter``
  documents exactly this call pattern as the way to unsubscribe.
* ``ActivityStream.recent(project_id=...)`` indexed a ``defaultdict``, so a read
  for an unknown project inserted a permanent empty deque.
* ``MetaAnalysisState.status`` was ``None`` on a field ``FlowState`` types as
  ``AgentStatus``. ``plan_act_flow.py:552`` reads it with
  ``getattr(state, "status", AgentStatus.IDLE)``, and the default never applies
  because the attribute exists and holds ``None``.
"""

from __future__ import annotations

import pytest

from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.core.activity_stream import ActivityStream
from weebot.domain.models.event import MessageEvent
from weebot.infrastructure.event_bus import AsyncEventBus


class TestSubscriptionsCanBeCancelled:
    @pytest.mark.asyncio
    async def test_subscribe_by_type_handler_can_be_unsubscribed(self):
        bus = AsyncEventBus(handler_timeout=None)
        seen: list = []

        async def handler(event):
            seen.append(event)

        bus.subscribe_by_type("message", handler)
        bus.unsubscribe(handler)
        await bus.publish(MessageEvent(role="user", message="hi"))

        assert seen == [], "an unsubscribed handler must stop receiving events"
        assert bus._handlers == []

    @pytest.mark.asyncio
    async def test_repeated_cycles_do_not_accumulate_handlers(self):
        """The leak was unbounded: one retained handler per subscribe/unsubscribe."""
        bus = AsyncEventBus(handler_timeout=None)

        for _ in range(100):

            async def handler(event):
                pass

            bus.subscribe_by_type("message", handler)
            bus.unsubscribe(handler)

        assert bus._handlers == []

    @pytest.mark.asyncio
    async def test_plain_subscribe_still_unsubscribes(self):
        bus = AsyncEventBus(handler_timeout=None)
        seen: list = []

        async def handler(event):
            seen.append(event)

        bus.subscribe(handler)
        bus.unsubscribe(handler)
        await bus.publish(MessageEvent(role="user", message="hi"))

        assert seen == []

    @pytest.mark.asyncio
    async def test_unsubscribing_one_handler_leaves_others_subscribed(self):
        """No-regression: unsubscribe must not clear the whole list."""
        bus = AsyncEventBus(handler_timeout=None)
        kept: list = []

        async def going(event):
            raise AssertionError("unsubscribed handler fired")

        async def staying(event):
            kept.append(event)

        bus.subscribe_by_type("message", going)
        bus.subscribe_by_type("message", staying)
        bus.unsubscribe(going)
        await bus.publish(MessageEvent(role="user", message="hi"))

        assert len(kept) == 1

    @pytest.mark.asyncio
    async def test_type_filtering_still_applies(self):
        """No-regression: the wrapper must still filter by event type."""
        bus = AsyncEventBus(handler_timeout=None)
        seen: list = []

        async def handler(event):
            seen.append(event)

        bus.subscribe_by_type("no_such_type", handler)
        await bus.publish(MessageEvent(role="user", message="hi"))

        assert seen == []

    @pytest.mark.asyncio
    async def test_unsubscribing_an_unknown_handler_is_a_no_op(self):
        bus = AsyncEventBus(handler_timeout=None)

        async def never_subscribed(event):
            pass

        bus.unsubscribe(never_subscribed)  # must not raise


class TestReadsDoNotAllocate:
    def test_recent_for_unknown_project_does_not_insert(self):
        stream = ActivityStream()

        for i in range(50):
            assert stream.recent(project_id=f"unknown-{i}") == []

        assert len(stream._by_project) == 0

    def test_recent_still_returns_a_known_project(self):
        """No-regression: filtering must still work."""
        stream = ActivityStream()
        stream.push("proj", "info", "hello")

        assert [e.message for e in stream.recent(project_id="proj")] == ["hello"]
        assert stream.recent(project_id="other") == []


class TestEveryFlowStateDeclaresAStatus:
    def _states(self):
        """Every concrete FlowState subclass, imported from the states package."""
        import importlib
        import pkgutil

        import weebot.application.flows.states as states_pkg

        found = {}
        for mod in pkgutil.iter_modules(states_pkg.__path__):
            module = importlib.import_module(f"{states_pkg.__name__}.{mod.name}")
            for name in dir(module):
                obj = getattr(module, name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, FlowState)
                    and obj is not FlowState
                ):
                    found[f"{mod.name}.{name}"] = obj
        return found

    def test_the_scan_finds_states(self):
        """Guard the guard: an empty scan would pass everything below."""
        assert len(self._states()) >= 8

    def test_no_state_declares_a_non_status(self):
        """`getattr(state, "status", AgentStatus.IDLE)` cannot rescue a None."""
        offenders = {
            name: cls.status
            for name, cls in self._states().items()
            if not isinstance(cls.status, AgentStatus)
        }
        assert offenders == {}, f"states with a non-AgentStatus status: {offenders}"

    def test_meta_analysis_state_specifically(self):
        from weebot.application.flows.states.meta_analysis import MetaAnalysisState

        assert MetaAnalysisState.status is AgentStatus.SUMMARIZING
        assert MetaAnalysisState.status.value == "summarizing"
