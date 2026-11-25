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
