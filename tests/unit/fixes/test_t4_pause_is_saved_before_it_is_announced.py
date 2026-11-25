"""X4: a reply to a question became mid-run steering, and steering leaked into the next run.

A pause event reached the client while the saved row still said RUNNING, so an answer sent at
once was dispatched as steering (and the question went unanswered). Pause events are now
saved WAITING before they are published, and steering still queued when a run ends is
reported instead of waiting for the next run.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.flows.event_publisher import PAUSE_EVENT_TYPES
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states import _step_run
from weebot.application.flows.states.plan_review import PlanReviewState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import (
    ErrorEvent,
    MessageEvent,
    PlanReviewEvent,
    ToolApprovalEvent,
    WaitForUserEvent,
)
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.adapters.steering_adapter import InMemorySteeringAdapter
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


class _Bus:
    """Records the stored status at the moment each event is published."""

    def __init__(self, repo):
        self._repo = repo
        self.seen: list[tuple[str, SessionStatus]] = []
        self.extras: list[dict] = []  # the stored context.extra at each publish

    async def publish(self, event):
        stored = await self._repo.load_session("s1")
        self.seen.append((event.type, stored.status if stored else None))
        self.extras.append(dict(stored.context.extra) if stored else {})

    async def publish_domain_event(self, event):
        return None


async def _flow(**kw):
    repo = InMemoryStateRepository()
    session = Session(id="s1", user_id="u", agent_id="a", status=SessionStatus.RUNNING)
    await repo.save_session(session)
    bus = _Bus(repo)
    return PlanActFlow(session=session, state_repo=repo, event_bus=bus, **kw), bus


def test_the_pause_types_are_the_events_that_ask_the_user_something():
    assert PAUSE_EVENT_TYPES == {"wait_for_user", "tool_approval", "plan_review"}


async def test_a_pause_event_is_saved_waiting_before_it_is_published():
    flow, bus = await _flow()
    flow._session = flow._session.set_status(SessionStatus.WAITING)
    await flow._emit(WaitForUserEvent(question="ok?"))
    assert bus.seen == [("wait_for_user", SessionStatus.WAITING)]


async def test_an_ordinary_event_is_still_published_before_it_is_saved():
    flow, bus = await _flow()
    flow._session = flow._session.set_status(SessionStatus.WAITING)
    await flow._emit(MessageEvent(message="hi"))
    assert bus.seen == [("message", SessionStatus.RUNNING)]  # saved after, not before


@pytest.mark.parametrize(
    "event",
    [
        WaitForUserEvent(question="ok?"),
        ToolApprovalEvent(tool_name="pay", reason="r", fingerprint="f"),
    ],
)
async def test_a_step_that_pauses_marks_waiting_before_its_event_goes_out(monkeypatch, event):
    flow, bus = await _flow()
    monkeypatch.setattr(_step_run, "_reconstruct", lambda raw: [event])

    async def send(_cmd):
        return SimpleNamespace(success=True, error=None, data={"events": [{}]})

    flow._mediator = SimpleNamespace(send=send)
    flow._tools = ToolCollection()
    flow._plan = Plan(steps=[Step(id="1", description="d")])
    run = await _step_run.run_step_command(flow, flow._plan.steps[0], "go")

    assert run.hitl_paused
    assert bus.seen == [(event.type, SessionStatus.WAITING)]
    if isinstance(event, ToolApprovalEvent):
        # What routes the reply as an approval must already be in the row a client reads.
        assert bus.extras[0].get("_user_gate_pending") == "tool_approval"
        assert bus.extras[0].get("_tool_approval_pending")


async def test_a_pause_that_cannot_be_saved_is_not_published():
    flow, bus = await _flow()

    async def broken_save(_session):
        raise OSError("disk full")

    flow._state_repo.save_session = broken_save
    flow._session = flow._session.set_status(SessionStatus.WAITING)
    with pytest.raises(OSError):
        await flow._emit(WaitForUserEvent(question="ok?"))
    assert bus.seen == []  # the client never saw a question over a stale row


async def test_an_ordinary_event_survives_a_failed_save():
    flow, bus = await _flow()

    async def broken_save(_session):
        raise OSError("disk full")

    flow._state_repo.save_session = broken_save
    await flow._emit(MessageEvent(message="hi"))  # logged, not raised, as before
    assert [t for t, _ in bus.seen] == ["message"]


async def test_a_plan_review_is_saved_waiting_before_the_plan_is_announced():
    flow, bus = await _flow()
    flow._plan = Plan(title="p", steps=[Step(id=str(i), description="d") for i in range(3)])
    events = [e async for e in PlanReviewState().execute(flow, "go")]

    assert any(isinstance(e, PlanReviewEvent) for e in events)
    assert ("plan_review", SessionStatus.WAITING) in bus.seen


async def test_steering_left_at_the_end_of_a_run_is_reported_not_kept():
    steering = InMemorySteeringAdapter()
    flow, _ = await _flow(steering=steering)
    await steering.send("s1", "use the other API")
    await flow._report_undelivered_steering()

    said = [e for e in flow._session.events if isinstance(e, ErrorEvent)]
    assert len(said) == 1 and "use the other API" in said[0].error
    assert said[0].error_code == "STEERING_NOT_DELIVERED"
    assert await steering.poll("s1") is None  # gone: the next run cannot read it
    # Not an assistant message: that would be truth-bound and stored as a fact.
    assert not [e for e in flow._session.events if isinstance(e, MessageEvent)]


async def test_no_steering_means_no_report():
    flow, _ = await _flow(steering=InMemorySteeringAdapter())
    await flow._report_undelivered_steering()
    assert not [e for e in flow._session.events if isinstance(e, ErrorEvent)]
