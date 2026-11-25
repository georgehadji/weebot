"""M3-D2: a budget or termination stop before any plan existed ended COMPLETED.

`CompletedState` took "no plan" as success and stored the stop reason only in the log, so the
UI showed a finished task that never started. A stop reason with no plan is now FAILED, with
the reason on the session and in the transcript. No plan and no reason stays COMPLETED (a
plain chat-style run that needed none).
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.termination.base import TerminationResult
from weebot.domain.models.event import DoneEvent, ErrorEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.session import Session, SessionStatus


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


class _Stop:
    def check(self, ctx):
        return TerminationResult(should_terminate=True, reason="budget exceeded")


async def _run(conditions):
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=Session(id="s1", task="t", status=SessionStatus.RUNNING),
            max_iterations=3,
            termination_conditions=conditions,
        )
    )
    return flow, [e async for e in flow.run("t")]


async def test_a_stop_before_a_plan_fails_the_run_with_its_reason():
    flow, events = await _run([_Stop()])

    assert flow._session.status == SessionStatus.FAILED
    assert "budget exceeded" in flow._session.context.extra["failure_reason"]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert [e.error_code for e in errors] == ["TERMINATED"]
    assert "budget exceeded" in errors[0].error
    assert [e.status for e in events if isinstance(e, DoneEvent)] == ["failed"]


async def test_a_run_with_no_plan_and_no_stop_reason_still_completes():
    from weebot.application.flows.states.completed import CompletedState

    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=Session(id="s1", task="t", status=SessionStatus.RUNNING),
            max_iterations=3,
        )
    )
    orig = flow.set_state
    flow.set_state = lambda _s: orig(CompletedState())
    events = [e async for e in flow.run("t")]

    assert flow._session.status == SessionStatus.COMPLETED
    assert [e.status for e in events if isinstance(e, DoneEvent)] == ["completed"]


class _GoalMet:
    def check(self, ctx):
        return TerminationResult(should_terminate=True, reason="text 'done' mentioned", goal_met=True)


async def test_a_goal_met_stop_before_a_plan_is_not_a_failure():
    flow, events = await _run([_GoalMet()])

    assert flow._session.status == SessionStatus.COMPLETED
    assert not [e for e in events if isinstance(e, ErrorEvent)]
    assert [e.status for e in events if isinstance(e, DoneEvent)] == ["completed"]


async def test_an_early_stop_scores_no_trajectory():
    calls = []

    async def send(command):
        calls.append(command)
        return types.SimpleNamespace(success=True, data={})

    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=Session(id="s1", task="t", status=SessionStatus.RUNNING),
            max_iterations=3,
            termination_conditions=[_Stop()],
            mediator=types.SimpleNamespace(send=send),
        )
    )
    [e async for e in flow.run("t")]

    assert calls == [], "a run that never started has no trajectory to score"


async def _seed(_session_id):
    return None


async def test_the_budget_gate_stop_before_a_plan_fails_with_budget_exceeded(monkeypatch):
    async def refused(_flow):
        return "stop", "BUDGET_EXCEEDED: refused at $1.00 (limit $1.00)"

    monkeypatch.setattr(
        "weebot.application.flows.collaborators.session_budget.budget_gate", refused
    )
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=Session(id="s1", task="t", status=SessionStatus.RUNNING),
            max_iterations=3,
            cost_meter=types.SimpleNamespace(seed=_seed),
        )
    )
    events = [e async for e in flow.run("t")]

    assert flow._session.status == SessionStatus.FAILED
    assert "BUDGET_EXCEEDED" in flow._session.context.extra["failure_reason"]
    assert [e.status for e in events if isinstance(e, DoneEvent)] == ["failed"]


async def test_a_stop_after_a_plan_exists_keeps_its_reason():
    plan = Plan(
        title="T",
        steps=[Step(id="s1", description="a"), Step(id="s2", description="b")],
    )
    session = Session(id="s1", task="t", status=SessionStatus.RUNNING).add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump(mode="json"))
    )
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=session,
            max_iterations=3,
            termination_conditions=[_Stop()],
        )
    )
    errors = [e async for e in flow.run("t") if isinstance(e, ErrorEvent)]

    assert flow._session.status == SessionStatus.FAILED
    assert [e.error_code for e in errors] == ["TERMINATED"]
    assert "budget exceeded" in errors[0].error and "steps not done" in errors[0].error
    assert "budget exceeded" in flow._session.context.extra["failure_reason"]
