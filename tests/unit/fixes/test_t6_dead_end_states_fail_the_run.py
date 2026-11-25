"""M3-D1: a state that yielded an error and returned without a transition left the session
RUNNING in the same state, so the loop re-entered it up to `max_iterations` times (repeating
any LLM call) and ended MAX_ITERATIONS, blaming the loop instead of the cause. Each such path
now ends the run FAILED after one pass, with its own reason on the session.
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.planning import PlanningState
from weebot.application.flows.states.updating import UpdatingState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.plan import Plan
from weebot.domain.models.session import Session, SessionStatus


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


def _counting(state_cls):
    """A subclass that counts how many times the loop enters it."""

    class Counted(state_cls):
        entered = 0

        async def execute(self, context, prompt):
            type(self).entered += 1
            async for event in super().execute(context, prompt):
                yield event

    return Counted


async def _run(state, *, plan=None, mediator=None):
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=Session(id="s1", task="a task", status=SessionStatus.RUNNING),
            max_iterations=20,
            mediator=mediator,
        )
    )
    def enter(_s, _orig=flow.set_state):
        flow._plan = plan  # begin_run resets the plan, so it is set as the state is entered
        _orig(state)

    flow.set_state = enter
    events = [e async for e in flow.run("a task")]
    return flow, [e for e in events if isinstance(e, ErrorEvent)]


def _failed_once(flow, errors, state_cls, code, reason_part):
    assert state_cls.entered == 1, "the loop must not re-enter a dead-end state"
    assert [e.error_code for e in errors] == [code]
    assert flow._session.status == SessionStatus.FAILED
    assert reason_part in flow._session.context.extra["failure_reason"]


async def test_executing_without_a_plan_fails_the_run():
    state = _counting(ExecutingState)
    flow, errors = await _run(state())
    _failed_once(flow, errors, state, "NO_PLAN", "No plan available during execution")


async def test_updating_without_a_plan_fails_the_run():
    state = _counting(UpdatingState)
    flow, errors = await _run(state())
    _failed_once(flow, errors, state, "NO_PLAN", "No plan available during update")


async def test_updating_a_plan_with_no_steps_fails_the_run():
    state = _counting(UpdatingState)
    flow, errors = await _run(state(), plan=Plan(title="t", steps=[]))
    _failed_once(flow, errors, state, "NO_STEPS", "No steps found in plan")


async def test_planning_without_a_mediator_fails_the_run():
    state = _counting(PlanningState)
    flow, errors = await _run(state())
    _failed_once(flow, errors, state, "NO_MEDIATOR", "requires a Mediator")


async def test_a_blocked_intent_fails_the_run_with_the_review_reason(monkeypatch):
    from weebot.domain.models.intent_review import IntentReview, IntentVerdict

    async def review(self, _contract):
        return IntentReview(verdict=IntentVerdict.BLOCKED, reasoning="asks for harm")

    monkeypatch.setattr(
        "weebot.application.services.intent_review_service.IntentReviewService.review", review
    )
    state = _counting(PlanningState)
    flow, errors = await _run(state(), mediator=types.SimpleNamespace(send=None))
    _failed_once(flow, errors, state, "INTENT_BLOCKED", "asks for harm")
