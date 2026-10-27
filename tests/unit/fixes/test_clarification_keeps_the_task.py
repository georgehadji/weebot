"""An answer to a pre-plan clarifying question is planned together with the task.

Found on a live web session ("Summarise the files in my Downloads folder"): intent
review asked three questions, the user answered, and the planner was sent the answer
alone, so the original task was no longer in the prompt.
"""

from __future__ import annotations

from weebot.application.flows.flow_router import FlowRouter
from weebot.application.flows.states.planning import PlanningState, with_clarification
from weebot.domain.models.session import Session, SessionContext, SessionStatus

TASK = "Summarise the files in my Downloads folder"
ANSWER = "windows 11, content-based summaries"


def _waiting_session(status=SessionStatus.WAITING) -> Session:
    from weebot.domain.models.event import WaitForUserEvent

    s = Session(id="s1", task=TASK, context=SessionContext(original_task=TASK))
    s = s.add_event(WaitForUserEvent(question="1. Which folder?"))
    return s.set_status(status)


def test_the_answer_is_kept_when_the_runner_already_set_running():
    # TaskRunner.resume_session sets RUNNING before the flow starts.
    _, session = FlowRouter.resolve_initial_state(_waiting_session(SessionStatus.RUNNING), ANSWER)
    assert session.context.get("_clarification_answer") == ANSWER


def test_the_router_keeps_the_answer_for_planning():
    state, session = FlowRouter.resolve_initial_state(_waiting_session(), ANSWER)
    assert isinstance(state, PlanningState)
    assert session.context.get("_clarification_answer") == ANSWER


def test_planning_puts_the_task_and_the_answer_together():
    _, session = FlowRouter.resolve_initial_state(_waiting_session(), ANSWER)
    prompt, session = with_clarification(session, ANSWER)
    assert TASK in prompt and ANSWER in prompt
    assert not session.context.get("_clarification_answer")  # used once


def test_a_fresh_task_is_left_alone():
    s = Session(id="s2", task=TASK, context=SessionContext(original_task=TASK))
    prompt, _ = with_clarification(s, TASK)
    assert prompt == TASK
