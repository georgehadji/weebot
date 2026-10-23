"""Answering the intent-review question must lead on to plan review.

Intent review pauses before any plan exists (`pause_for_user` in
PlanningState). The resume reaches FlowRouter's last branch, which returned
PlanningState with the session still WAITING, and the run loop breaks on
WAITING after every state. So the flow planned once and ended: no plan
review, no execution, exit 0. Seen live in the W3.7 observe batch.
"""

from __future__ import annotations

from weebot.application.flows.flow_router import FlowRouter
from weebot.application.flows.states.planning import PlanningState
from weebot.domain.models.session import Session, SessionStatus


def test_a_waiting_session_without_a_plan_resumes_planning_as_running():
    session = Session(id="sess-intent", title="t").set_status(SessionStatus.WAITING)

    state, updated = FlowRouter.resolve_initial_state(
        session=session, prompt="only the new files", extra=session.context.extra
    )

    assert isinstance(state, PlanningState)
    assert updated.status == SessionStatus.RUNNING


def test_a_fresh_session_keeps_its_status():
    session = Session(id="sess-fresh", title="t")

    _, updated = FlowRouter.resolve_initial_state(
        session=session, prompt="do a thing", extra=session.context.extra
    )

    assert updated.status == session.status
