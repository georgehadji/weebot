"""Tests for T1.6 — TaskRunner emits SessionPresenceEvent on status transitions.

The session rail needs to know about every session's status without
polling — this proves the three transitions TaskRunner drives (start →
RUNNING, success → COMPLETED, crash → FAILED) each publish exactly one
SessionPresenceEvent on the global channel (about_session_id set,
session_id left empty so the broadcaster routes it globally, not to one
session's own socket — see SessionPresenceEvent's docstring).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.event import DoneEvent, SessionPresenceEvent
from weebot.domain.models.session import Session, SessionStatus


class _StubFlow:
    def __init__(self, events, done: bool = True, raise_error: bool = False):
        self._events = events
        self._done = done
        self._raise_error = raise_error
        self._session = None

    async def run(self, prompt: str):
        if self._raise_error:
            raise RuntimeError("boom")
        for event in self._events:
            yield event

    def is_done(self) -> bool:
        return self._done

    async def teardown(self) -> None:
        pass


def _make_runner(session: Session, event_bus):
    state_repo = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=session)
    state_repo.save_session = AsyncMock()
    runner = TaskRunner(state_repo=state_repo, event_bus=event_bus)
    return runner, state_repo


@pytest.mark.asyncio
async def test_start_direct_publishes_running_presence():
    session = Session(id="s1", user_id="u", agent_id="a", title="My task")
    event_bus = AsyncMock()
    runner, _ = _make_runner(session, event_bus)

    flow = _StubFlow([DoneEvent()])
    await runner.start_session(session, lambda s: flow)

    presence_calls = [
        c.args[0] for c in event_bus.publish.await_args_list
        if isinstance(c.args[0], SessionPresenceEvent)
    ]
    assert any(p.status == "running" and p.about_session_id == "s1" for p in presence_calls)
    # SessionPresenceEvent must not carry a routing session_id — it needs
    # to reach the global rail, not just this session's own socket.
    assert all(p.session_id == "" for p in presence_calls)


@pytest.mark.asyncio
async def test_successful_flow_publishes_completed_presence():
    session = Session(id="s2", user_id="u", agent_id="a")
    event_bus = AsyncMock()
    runner, _ = _make_runner(session, event_bus)

    flow = _StubFlow([DoneEvent()], done=True)
    await runner.start_session(session, lambda s: flow)
    await runner._tasks["s2"]  # wait for the background task to finish

    presence_calls = [
        c.args[0] for c in event_bus.publish.await_args_list
        if isinstance(c.args[0], SessionPresenceEvent)
    ]
    assert any(p.status == "completed" for p in presence_calls)


@pytest.mark.asyncio
async def test_crashed_flow_publishes_failed_presence():
    session = Session(id="s3", user_id="u", agent_id="a")
    event_bus = AsyncMock()
    runner, _ = _make_runner(session, event_bus)
    runner._max_session_retries = 0  # no retry — fail immediately

    flow = _StubFlow([], raise_error=True)
    await runner.start_session(session, lambda s: flow)
    task = runner._tasks.get("s3")
    if task:
        await task

    presence_calls = [
        c.args[0] for c in event_bus.publish.await_args_list
        if isinstance(c.args[0], SessionPresenceEvent)
    ]
    assert any(p.status == "failed" for p in presence_calls)


@pytest.mark.asyncio
async def test_no_event_bus_does_not_raise():
    session = Session(id="s4", user_id="u", agent_id="a")
    state_repo = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=session)
    state_repo.save_session = AsyncMock()
    runner = TaskRunner(state_repo=state_repo, event_bus=None)

    flow = _StubFlow([DoneEvent()])
    await runner.start_session(session, lambda s: flow)  # must not raise
