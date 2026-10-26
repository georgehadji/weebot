"""Phase 4.0 of the 2026-10 wave 2 plan (WB-06): the executor loop, pinned by script.

`ExecutingState.execute` is 509 lines and `ExecutorAgent.execute_step` is 527. Both are
slated for extraction (phase 4.1/4.2 of
`tasks/specs/arch_audit_2026_10_wave2_remediation_plan.md`), and the reason that has not
happened is stated in the plan: the loop has no test that would notice it being reordered.
This is that test.

It drives the real `ExecutingState` against a scripted mediator, so nothing here needs a
model, a network or a database. What it pins is *ordering and routing*, which is what an
extraction can silently break:

  success              -> step COMPLETED, next state EXECUTING (more steps) or VERIFYING
  tool error           -> severity routing, never a silent completion
  cascade exhaustion   -> step UNVERIFIED and NO replan (all models tripped means
                          replanning would fail too)
  repetition trip      -> stops before the mediator is called at all
  steering             -> reaches the command's user_input (the P3-2 defect)

Events the state consumes come back from the mediator as dicts (`event.model_dump()`), the
same path `ExecuteStepHandler` uses, so `reconstruct_events` is exercised rather than
bypassed.
"""

from __future__ import annotations

import pytest

from weebot.application.cqrs.base import CommandResult
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import ErrorEvent, MessageEvent, ToolEvent
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session, SessionStatus

CASCADE_TRIPPED = "All models in the cascade have tripped"


class _LLM:
    """Never called: the mediator is scripted, so no model runs."""

    async def chat(self, **_kwargs):  # pragma: no cover - a call here is the failure
        raise AssertionError("the scripted mediator must not reach a model")


class ScriptedMediator:
    """Records commands and answers with canned events."""

    def __init__(self, *, events=None, success=True, error=None, token_usage=None):
        self.sent: list[object] = []
        self._events = list(events or [])
        self._success = success
        self._error = error
        self._token_usage = token_usage or {"prompt_tokens": 10, "completion_tokens": 5}

    async def send(self, command):
        self.sent.append(command)
        return CommandResult(
            success=self._success,
            data={"events": self._events, "token_usage": self._token_usage, "skill_gaps": []},
            error=self._error,
        )


def _flow(*, mediator, steps=None, steering=None, max_repetitions=3) -> PlanActFlow:
    session = Session(id="s-4-0", status=SessionStatus.RUNNING)
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=session,
            mediator=mediator,
            steering=steering,
            max_step_repetitions=max_repetitions,
        )
    )
    flow._plan = Plan(
        goal="g",
        title="t",
        steps=steps or [Step(id="s1", description="do the thing", status=StepStatus.PENDING)],
    )
    return flow


async def _run(flow: PlanActFlow) -> list:
    return [event async for event in ExecutingState().execute(flow, "the prompt")]


def _step(flow: PlanActFlow, step_id: str = "s1") -> Step:
    return next(s for s in flow._plan.steps if s.id == step_id)


def _state_name(flow: PlanActFlow) -> str:
    return type(flow._state).__name__


@pytest.mark.asyncio
async def test_a_successful_step_completes_and_moves_on():
    mediator = ScriptedMediator(
        events=[
            MessageEvent(
                role="assistant",
                message="Wrote the file and verified its contents end to end.",
            ).model_dump()
        ]
    )
    flow = _flow(mediator=mediator, steps=[
        Step(id="s1", description="first", status=StepStatus.PENDING),
        Step(id="s2", description="second", status=StepStatus.PENDING),
    ])

    events = await _run(flow)

    assert len(mediator.sent) == 1, "exactly one step executed"
    assert _step(flow, "s1").status == StepStatus.COMPLETED
    assert "Wrote the file" in (_step(flow, "s1").result or "")
    assert any(isinstance(e, MessageEvent) for e in events), "the step's events reach the caller"
    assert _state_name(flow) == "ExecutingState", "a pending step remains, so the loop continues"


@pytest.mark.asyncio
async def test_the_last_step_completed_moves_to_verifying():
    mediator = ScriptedMediator(events=[MessageEvent(role="assistant", message="Wrote the file and verified its contents end to end.").model_dump()])
    flow = _flow(mediator=mediator)  # one step only

    await _run(flow)

    assert _step(flow).status == StepStatus.COMPLETED
    assert _state_name(flow) == "VerifyingState", "nothing is pending, so the run verifies"


@pytest.mark.asyncio
async def test_a_tool_error_routes_through_severity_and_never_completes_silently():
    mediator = ScriptedMediator(
        events=[ToolEvent(tool_name="bash", result="", error="syntax error").model_dump()]
    )
    flow = _flow(mediator=mediator)

    await _run(flow)

    assert _step(flow).status != StepStatus.COMPLETED, "a failed step is not a completed step"
    assert _state_name(flow) in ("UpdatingState", "PlanningState", "ExecutingState")
    assert _state_name(flow) != "VerifyingState" or _step(flow).status == StepStatus.UNVERIFIED


@pytest.mark.asyncio
async def test_all_models_tripped_marks_unverified_and_skips_the_replan():
    """Replanning needs a model. When every model is circuit-broken it would fail too,
    so the step is recorded UNVERIFIED and the run goes straight to verifying."""
    mediator = ScriptedMediator(
        events=[ErrorEvent(error=f"{CASCADE_TRIPPED}: no model available").model_dump()]
    )
    flow = _flow(mediator=mediator)

    await _run(flow)

    assert _step(flow).status == StepStatus.UNVERIFIED
    assert "circuit-broken" in (_step(flow).result or "")
    assert _state_name(flow) == "VerifyingState"
    assert len(mediator.sent) == 1, "no second attempt was made"


@pytest.mark.asyncio
async def test_the_repetition_limit_stops_before_calling_the_mediator():
    mediator = ScriptedMediator()
    flow = _flow(mediator=mediator, max_repetitions=2)
    # Pretend this step already ran twice.
    flow._step_execution_counts["s1"] = 2

    events = await _run(flow)

    assert mediator.sent == [], "the loop stopped before spending a model call"
    assert any(isinstance(e, ErrorEvent) for e in events), "the stop is reported, not silent"
    assert _state_name(flow) == "VerifyingState"


class _Steering:
    def __init__(self, message: str) -> None:
        self._message = message

    async def poll(self, _session_id: str):
        return self._message


@pytest.mark.asyncio
async def test_steering_reaches_the_command():
    """P3-2: the command was built from the original prompt, so a steering message was
    polled, logged, and dropped."""
    mediator = ScriptedMediator(events=[MessageEvent(role="assistant", message="Wrote the file and verified its contents end to end.").model_dump()])
    flow = _flow(mediator=mediator, steering=_Steering("use the other endpoint"))

    await _run(flow)

    sent = mediator.sent[0]
    assert "use the other endpoint" in sent.user_input
    assert "STEERING" in sent.user_input


@pytest.mark.asyncio
async def test_a_rejected_command_transitions_without_completing():
    mediator = ScriptedMediator(success=False, error="handler refused")
    flow = _flow(mediator=mediator)

    events = await _run(flow)

    assert _step(flow).status != StepStatus.COMPLETED
    assert _state_name(flow) == "UpdatingState"
    assert any(isinstance(e, ErrorEvent) for e in events)
