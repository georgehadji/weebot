"""AUTO execution mode: the same flow with no human in the loop.

Pinned here because "skip every pause" is easy to implement inconsistently: each gate
lives in its own module, and one forgotten gate leaves a `flow run --auto` silently
waiting for an answer nobody will type. Every pause site that AUTO must bypass gets a
test, plus the parser that turns the CLI flag into the mode.
"""

from __future__ import annotations

import pytest

from weebot.application.cqrs.base import CommandResult
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states._execution_gates import _constraint_gate, _inbound_mail_gate
from weebot.application.flows.states._step_outcome import quality_gate
from weebot.application.flows.states._step_run import StepRun
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.plan_review import PlanReviewState
from weebot.application.flows.states.product_gate import ProductGateState
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
from weebot.application.services.tool_approval import AutoApproval
from weebot.domain.models.event import ToolApprovalEvent, WaitForUserEvent
from weebot.domain.models.execution_mode import ExecutionMode
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session, SessionStatus


class _LLM:
    """Never called: the mediator is scripted, so no model runs."""

    async def chat(self, **_kwargs):  # pragma: no cover - a call here is the failure
        raise AssertionError("the scripted mediator must not reach a model")


class ScriptedMediator:
    def __init__(self, *, events=None, success=True):
        self.sent: list[object] = []
        self._events = list(events or [])
        self._success = success

    async def send(self, command):
        self.sent.append(command)
        return CommandResult(
            success=self._success,
            data={"events": self._events, "token_usage": {}, "skill_gaps": []},
        )


def _flow(*, mediator=None, mode=ExecutionMode.AUTO, steps=None) -> PlanActFlow:
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(),
            tools=ToolCollection(),
            session=Session(id="s-auto", status=SessionStatus.RUNNING),
            mediator=mediator or ScriptedMediator(),
            execution_mode=mode,
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


def test_from_flag_parses_the_cli_flag():
    assert ExecutionMode.from_flag(None) is ExecutionMode.INTERACTIVE
    assert ExecutionMode.from_flag("auto") is ExecutionMode.AUTO
    assert ExecutionMode.from_flag("AUTO") is ExecutionMode.AUTO
    assert ExecutionMode.from_flag(" yes ") is ExecutionMode.AUTO
    assert ExecutionMode.from_flag("interactive") is ExecutionMode.INTERACTIVE
    assert ExecutionMode.from_flag("nonsense") is ExecutionMode.INTERACTIVE


@pytest.mark.asyncio
async def test_auto_approval_grants_every_ask():
    request = ToolCallApproval(
        session_id="s-auto",
        tool_name="bash",
        arguments={"command": "Get-ChildItem"},
        fingerprint="fp",
        guard="shell_guard",
        reason="needs approval",
    )

    assert await AutoApproval().resolve(request) is ApprovalOutcome.APPROVED


@pytest.mark.asyncio
async def test_inbound_mail_gate_does_not_pause_in_auto():
    flow = _flow()
    flow._session = flow._session.set_fact("atomic_mail_inbound_pending", True)

    event = await _inbound_mail_gate(flow)

    assert event is None, "no WaitForUserEvent in AUTO"
    assert not flow._session.get_fact("atomic_mail_inbound_pending"), "the gate clears the flag"
    assert flow._session.context.get("_user_gate_pending") is None, "nothing is waiting"


@pytest.mark.asyncio
async def test_constraint_gate_does_not_pause_in_auto(monkeypatch):
    flow = _flow()
    flow._execution_mode = ExecutionMode.AUTO
    step = _step(flow)

    class _Violation:
        text = "always use tabs"

    monkeypatch.setattr(
        ExecutingState, "_constraint_violations", staticmethod(lambda *a, **k: [_Violation()])
    )
    monkeypatch.setattr(
        ExecutingState, "_journal_constraint_violation", staticmethod(_noop_async),
    )

    event = await _constraint_gate(ExecutingState(), flow, step, "the prompt")

    assert event is None, "the step proceeds without asking"
    assert flow._session.get_fact(f"constraint_gate_ack:{step.id}"), "the violation is acknowledged"
    assert flow._session.context.get("_user_gate_pending") is None


async def _noop_async(*_args, **_kwargs) -> None:
    return None


def test_quality_gate_allows_a_failure_through_in_auto(monkeypatch):
    from weebot.application.services.step_result_validator import ValidationResult

    monkeypatch.setattr(
        "weebot.application.services.step_result_validator.StepResultValidator.validate",
        lambda *a, **k: ValidationResult(passed=False, reason="too short", quality_hint="expand"),
    )
    flow = _flow()
    step = _step(flow)

    forced_retry = quality_gate(flow, step, StepRun(result_text="x"))

    assert forced_retry is False, "AUTO does not retry on a quality failure"
    assert _step(flow).retry_count == 0
    assert _step(flow).status == StepStatus.PENDING, "the step was not replaced for a retry"


@pytest.mark.asyncio
async def test_a_hitl_step_is_completed_not_paused_in_auto():
    mediator = ScriptedMediator(
        events=[WaitForUserEvent(question="Which account?").model_dump()]
    )
    flow = _flow(mediator=mediator)

    await _run(flow)

    assert _step(flow).status == StepStatus.COMPLETED, "the plan moves on"
    assert flow._session.status != SessionStatus.WAITING, "AUTO never leaves the session waiting"
    assert flow._session.context.get("_user_gate_pending") is None


@pytest.mark.asyncio
async def test_a_tool_approval_does_not_pause_in_auto():
    mediator = ScriptedMediator(
        events=[ToolApprovalEvent(tool_name="bash", reason="needs approval").model_dump()]
    )
    flow = _flow(mediator=mediator)

    await _run(flow)

    assert _step(flow).status == StepStatus.COMPLETED
    assert flow._session.status != SessionStatus.WAITING
    assert flow._session.context.get("_tool_approval_pending") is None


@pytest.mark.asyncio
async def test_plan_review_is_skipped_in_auto():
    flow = _flow(
        steps=[
            Step(id="s1", description="first", status=StepStatus.PENDING),
            Step(id="s2", description="second", status=StepStatus.PENDING),
        ]
    )

    events = [e async for e in PlanReviewState(min_steps=1).execute(flow, "the prompt")]

    assert events == [], "no PlanReviewEvent, no WaitForUserEvent"
    assert type(flow._state).__name__ == "ExecutingState"
    assert flow._session.status != SessionStatus.WAITING


@pytest.mark.asyncio
async def test_product_gate_is_skipped_in_auto():
    flow = _flow()

    events = [
        e
        async for e in ProductGateState().execute(
            flow, "build me a small tool that renames files"
        )
    ]

    assert events == []
    assert type(flow._state).__name__ == "PlanningState"
    assert flow._session.status != SessionStatus.WAITING


@pytest.mark.asyncio
async def test_interactive_mode_still_pauses_on_hitl():
    """The guard on the guard: AUTO must not have disabled the interactive path."""
    mediator = ScriptedMediator(
        events=[WaitForUserEvent(question="Which account?").model_dump()]
    )
    flow = _flow(mediator=mediator, mode=ExecutionMode.INTERACTIVE)

    await _run(flow)

    assert flow._session.status == SessionStatus.WAITING
    assert _step(flow).status != StepStatus.COMPLETED
