"""With a bus, AgentRunner publishes each event once.

The flow's `_emit` already publishes what it emits; the runner republished
every yielded event, so emitted-then-yielded events reached the bus twice
(two terminal lines per step in `flow run`). Yield-only events still need
the runner's publish.
"""

from __future__ import annotations

from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session
from weebot.interfaces.cli import agent_runner as ar


class _Bus:
    def __init__(self):
        self.ids = []

    async def publish(self, event):
        self.ids.append(event.id)

    def subscribe(self, *a, **k):
        return None


class _Repo:
    async def save_session(self, s):
        return None

    async def load_session(self, sid):
        return None


async def test_emitted_events_are_not_republished(monkeypatch):
    bus = _Bus()
    emitted = MessageEvent(role="assistant", message="emitted")
    yielded_only = MessageEvent(role="assistant", message="yield only")

    class _Flow:
        def __init__(self, session):
            self._session = session

        async def run(self, prompt):
            self._session = self._session.add_event(emitted)
            await bus.publish(emitted)  # what _emit does
            yield emitted
            yield yielded_only

        def is_done(self):
            return False

    async def _tools(**_):
        return None

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(ar, "build_tools", _tools)
    monkeypatch.setattr(ar, "create_flow", lambda **kw: _Flow(kw["session"]))
    monkeypatch.setattr("weebot.core.behavior_integration.start_session_tracking_async", _none)
    monkeypatch.setattr("weebot.core.behavior_integration.stop_session_tracking_async", _none)

    runner = ar.AgentRunner(llm=object(), state_repo=_Repo(), event_bus=bus, use_rich=False)
    async for _ in runner.run_prompt("hello"):
        pass
    assert bus.ids.count(emitted.id) == 1
    assert bus.ids.count(yielded_only.id) == 1
