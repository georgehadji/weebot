"""Run one step through the CQRS mediator (WB-06, phase 4.1).

Extracted from `ExecutingState.execute`, which was 509 lines. This is the part that spends
money and touches the session, so it is the part that most deserves to be readable on its
own: exactly one command is sent, its events are reconstructed from the serialised form
`ExecuteStepHandler` returns, and the two security-relevant facts they carry (a human is
needed; untrusted mail arrived) are read here rather than after a scroll.

The events are collected and returned, not yielded, because by the time the mediator
returns every event already exists -- the handler ran the step to completion. The caller
emits and yields them, which is also where the ordering with post-step gates lives.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from weebot.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    MessageEvent,
    ToolApprovalEvent,
    ToolEvent,
    WaitForUserEvent,
)

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.domain.models.plan import Step

logger = logging.getLogger(__name__)


@dataclass
class StepRun:
    """What one mediated step produced.

    ``rejected`` is set when nothing ran at all (no mediator, or the handler refused), and
    the caller turns it into an ErrorEvent. Otherwise ``events`` holds the step's events and
    the flags summarise them.
    """

    rejected: str | None = None
    events: list[AgentEvent] = field(default_factory=list)
    hitl_paused: bool = False
    execution_failed: bool = False
    should_terminate: bool = False
    result_text: str = ""
    elapsed_s: float = 0.0
    skills_used: list[str] = field(default_factory=list)  # candidate skills in the prompt


async def run_step_command(context: PlanActFlow, step: Step, effective_prompt: str) -> StepRun:
    """Send ExecuteStepCommand and classify what came back."""
    if context._mediator is None:
        return StepRun(
            rejected=(
                "ExecutingState requires a Mediator to be configured on PlanActFlow. "
                "Construct PlanActFlow with mediator=container.get(Mediator) or "
                'build it through container.get("create_flow").'
            )
        )

    from weebot.application.cqrs.commands import ExecuteStepCommand
    from weebot.config.model_refs import MODEL_BUDGET

    started = time.monotonic()
    cmd_result = await context._mediator.send(
        ExecuteStepCommand(
            session_id=context._session.id,
            step_id=step.id,
            model=context._model or MODEL_BUDGET,
            tools=[t.name for t in context._tools],
            # `effective_prompt`, not the raw prompt: this sent the ORIGINAL, so steering
            # was polled, logged and dropped (P3-2 in the audit).
            user_input=effective_prompt,
            step_context=context.step_execution_context(),  # ADR-015
        )
    )
    elapsed = time.monotonic() - started

    if not cmd_result.success:
        return StepRun(rejected=cmd_result.error or "step execution rejected", elapsed_s=elapsed)

    data = cmd_result.data or {}
    context.record_step_usage(data.get("token_usage"), data.get("skill_gaps"))

    run = StepRun(elapsed_s=elapsed, skills_used=list(data.get("skills_used") or []))
    for event in _reconstruct(data.get("events", [])):
        run.events.append(event)
        await context._emit(event)
        if isinstance(event, WaitForUserEvent):
            run.hitl_paused = True
        elif isinstance(event, ToolApprovalEvent):
            run.hitl_paused = True
            # ADR-013: record what a "yes" approves; FlowRouter grants it.
            from weebot.application.services.tool_approval import mark_tool_approval_pending

            context._session = mark_tool_approval_pending(context._session, event)
        elif isinstance(event, ErrorEvent):
            run.execution_failed = True
        if getattr(event, "type", "") == "tool" and getattr(event, "tool_name", "") == "terminate":
            run.should_terminate = True

    # ADR 006: if this step read an inbox, the NEXT step is gated through approval_policy.
    if step_fetched_inbound_mail(run.events):
        context._session = context._session.set_fact("atomic_mail_inbound_pending", True)

    run.result_text = _longest_output(run.events)
    return run


def _reconstruct(raw: list[dict[str, Any]]) -> list[AgentEvent]:
    from weebot.application.cqrs.event_reconstructor import reconstruct_events

    return reconstruct_events(raw)


def step_fetched_inbound_mail(events: list[Any]) -> bool:
    """Return True if any event is a completed atomic_mail jmap_request.

    Used to flag a session so the NEXT step is gated through approval_policy
    before the agent can act on untrusted inbound email content (ADR 006 / R1).

    A jmap_request is the read path (list/fetch/search mail); register and help
    do not return inbound content and are not gated.

    Moved here from the state module, unchanged, so the module that sets the flag also
    owns the predicate that decides it.
    """
    for e in events:
        if (
            isinstance(e, ToolEvent)
            and e.tool_name == "atomic_mail"
            and e.status.value == "called"
            and (not e.function_args or e.function_args.get("action") == "jmap_request")
        ):
            return True
    return False


def _longest_output(events: list[AgentEvent]) -> str:
    """The step's result as the longest assistant message or tool output it produced."""
    best = ""
    for event in events:
        if isinstance(event, MessageEvent) and getattr(event, "role", "") == "assistant":
            text = getattr(event, "message", "") or ""
        elif isinstance(event, ToolEvent):
            text = getattr(event, "result", "") or ""
        else:
            continue
        if text and len(text) > len(best):
            best = text
    return best


async def record_skill_uses(context: PlanActFlow, step, run: StepRun, *, passed: bool) -> None:
    """Count each candidate skill the step used toward promotion or quarantine.

    Best-effort: counting a use must never fail the step.
    """
    names = list(getattr(run, "skills_used", None) or [])
    if not names or context._mediator is None:
        return
    from weebot.application.cqrs.commands.validation_commands import RecordSkillUseCommand

    for name in names:
        try:
            await context._mediator.send(
                RecordSkillUseCommand(
                    skill_name=name, session_id=context._session.id, step_id=step.id, passed=passed
                )
            )
        except Exception:
            logger.warning("Could not record a use of skill %s", name, exc_info=True)
