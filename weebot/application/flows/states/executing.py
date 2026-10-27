"""Executing state for Plan-Act flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from collections.abc import AsyncGenerator

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.domain.services.session_lessons import project_key
from weebot.application.flows.states.base import (
    AgentStatus,
    FlowState,
    StateId,
    new_state,
    register_state,
)
from weebot.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    PlanEvent,
)
from weebot.domain.models.plan import Step, StepStatus

from weebot.application.flows.states._execution_gates import apply_pre_step_gates
from weebot.application.flows.states._step_outcome import (
    absorb_step_result,
    complete_step,
    error_hooks,
    next_transition,
    pause_for_human,
    post_task_hooks,
    pre_task_hooks,
    progress_gate,
    quality_gate,
    route_failure,
)
from weebot.application.flows.states._step_run import record_skill_uses, run_step_command

logger = logging.getLogger(__name__)

# The code-step detection helpers, `mark_user_gate` and `step_fetched_inbound_mail`
# moved to `_step_outcome.py` and `_step_run.py` with the code that uses them (WB-06).


@register_state(StateId.EXECUTING)
class ExecutingState(FlowState):
    """Handles the execution of individual steps in the plan."""

    status = AgentStatus.EXECUTING

    # ── Browser invocation audit ───────────────────────────────────

    @staticmethod
    def _audit_browser_invocation(context: PlanActFlow) -> None:
        """Post-execution check: if plan mentions browser tools but none were invoked, warn.

        Scans plan step descriptions for browser-related keywords. If any match,
        checks session events for actual browser_navigator or advanced_browser calls.
        Emits WARNING if the plan expected browser interaction but none occurred.
        """
        _browser_kw = {
            "browser_navigator",
            "advanced_browser",
            "web_scraper",
            "browser_inspector",
            "navigate",
            "click",
            "fill",
            "screenshot",
            "compose",
            "login",
        }
        _plan = getattr(context, "_plan", None)
        if _plan is None or not hasattr(_plan, "steps"):
            return

        _plan_has_browser = any(
            any(kw in (s.description or "").lower() for kw in _browser_kw) for s in _plan.steps
        )
        if not _plan_has_browser:
            return

        # Check session events for browser tool calls
        _session = getattr(context, "_session", None)
        if _session is None:
            return

        _browser_called = any(
            getattr(e, "type", "") == "tool"
            and getattr(e, "tool_name", "") in ("browser_navigator", "advanced_browser")
            for e in _session.events
        )

        if not _browser_called:
            import logging as _log

            _log.getLogger("weebot.application.flows.states.executing").warning(
                "Plan contains browser-related steps (%d browser keywords found), "
                "but no browser tool was invoked during execution. "
                "The model may not support browser tool calls. "
                "Consider using a model with higher tool-use capability.",
                sum(
                    1
                    for s in _plan.steps
                    for kw in _browser_kw
                    if kw in (s.description or "").lower()
                ),
            )

    # ── Constraint enforcement gate (Lost-in-Compaction Phase 5.4) ─────

    @staticmethod
    def _constraint_violations(context: PlanActFlow, step: Step, prompt: str) -> list:
        """Return the constraints *step* appears to violate, or an empty list.

        Prefers the session-constraint registry, which accumulates every user
        turn (start, resume, steering) and honours revocation and direction.
        Falls back to regex over the original task only when the registry is
        empty — i.e. when no extractor is wired.

        Why the registry has to be first: the legacy expression
        ``original_task or last_prompt or prompt`` always resolves to
        ``original_task``, which is written in exactly one place and only when
        the opening prompt is non-empty. A constraint the user stated on turn
        five was therefore invisible to this gate forever, and gateway/chat
        sessions never populated it at all.

        Direction filtering happens in ``compile_enforceable``: a LOOSEN
        constraint must never reach here. Before that filter existed, the
        paper's SC#1 — "don't ask me to confirm, just do it" — made this gate
        pause to ask for confirmation, violating the constraint it was
        enforcing.
        """
        import os

        if os.environ.get("CONSTRAINT_CHECK_ENABLED", "").lower() == "false":
            return []

        from weebot.application.services.constraint_compilers import compile_from_flow
        from weebot.application.services.constraint_extractor import ConstraintExtractor

        extractor = ConstraintExtractor()
        constraints = compile_from_flow(context)
        if not constraints:
            source = (
                context._session.context.get("original_task", "")
                or context._session.context.get("last_prompt", "")
                or prompt
            )
            if not source:
                return []
            constraints = extractor.extract(source)
        return extractor.check_step(step.description, constraints)

    async def _evidence_gate(
        self, context, step: Step, step_events: list, step_elapsed: float
    ) -> PlanEvent | None:
        from weebot.application.flows.states.evidence_gate import evidence_gate

        return await evidence_gate(context, step, step_events, step_elapsed)

    @staticmethod
    async def _journal_constraint_violation(
        context: PlanActFlow, step: Step, constraint_text: str
    ) -> None:
        """Record the pause in the misalignment journal, best-effort.

        Awaited rather than fire-and-forget: the previous ``ensure_future``
        was never awaited and never had its exception retrieved, so a failing
        journal wrote nothing and logged nothing. The write must not be able
        to block the gate, hence the broad except.
        """
        journal = getattr(context, "_misalignment_journal", None)
        if journal is None:
            return
        try:
            from weebot.domain.models.misalignment_entry import MisalignmentEntry

            await journal.record(
                MisalignmentEntry(
                    session_id=context._session.id,
                    project_path=project_key(context._session.context.get("working_dir")),
                    symptom="constraint_violation",
                    constraint_text=constraint_text,
                    step_description=step.description,
                )
            )
        except Exception as exc:
            logger.warning("Misalignment journal write failed: %s", exc)

    async def execute(self, context: PlanActFlow, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        """Advance one step, then decide where the flow goes next.

        This method is the *order* of the loop and nothing else: the gates before a step
        live in `_execution_gates`, the mediated call and its event classification in
        `_step_run`, and every post-step decision in `_step_outcome`. It was 509 lines
        with all of that inline (WB-06 in
        tasks/specs/arch_audit_2026_10_wave2_remediation_plan.md), which made an ordering
        change indistinguishable from a routing change in review.
        """
        if context._plan is None:
            yield ErrorEvent(error="No plan available during execution")
            return

        step = context._plan.get_next_step()
        if step is None:
            logger.info("All steps complete, transitioning to VERIFYING")
            context.set_state(new_state(StateId.VERIFYING))
            return

        # Check if step was already completed (prevent re-execution)
        if step.status == StepStatus.COMPLETED:
            logger.warning("Step %s already completed, skipping", step.id)
            context.set_state(new_state(StateId.UPDATING))
            return

        gate = await apply_pre_step_gates(self, context, step, prompt)
        if gate.event is not None:
            yield gate.event
            return
        if gate.stop:
            return

        # A step cannot run without a mediator: the executor is reached through it.
        if context._mediator is None:
            yield ErrorEvent(
                error=(
                    "ExecutingState requires a Mediator to be configured on PlanActFlow. "
                    "Construct PlanActFlow with mediator=container.get(Mediator) or "
                    'build it through container.get("create_flow").'
                )
            )
            context.set_state(new_state(StateId.UPDATING))
            return

        # Mark step as RUNNING before execution so the executor and
        # mediator see the correct state.
        context._plan = context._plan.update_step_status(step.id, StepStatus.RUNNING)
        logger.info("Executing step %s: %s", step.id, step.description)
        await pre_task_hooks(context, step)

        run = await run_step_command(context, step, gate.effective_prompt)
        for event in run.events:
            yield event

        if run.rejected is not None:
            yield ErrorEvent(error=f"Step execution rejected: {run.rejected}")
            context.set_state(new_state(StateId.UPDATING))
            return

        # The step's own output, carried on the step for the gates and the audit below.
        step = step.model_copy(update={"result": run.result_text or None})

        if run.hitl_paused:
            logger.info("Step %s paused for human input after %.1fs", step.id, run.elapsed_s)
            await post_task_hooks(context, step, run)
            pause_for_human(context)
            return

        if run.execution_failed:
            await record_skill_uses(context, step, run, passed=False)
            await error_hooks(context, step)
            stopped = await route_failure(context, step, run)
            if stopped is not None:
                yield stopped
            return

        if quality_gate(context, step, run):
            return
        if await progress_gate(context, step, run):
            return

        # LongHorizon-Harness E1: environment-grounded evidence gate. Runs BEFORE
        # completion is committed, scoped to this step's events, not the whole session.
        audit_event = await self._evidence_gate(context, step, run.events, run.elapsed_s)
        if audit_event is not None:
            yield audit_event
            return

        complete_step(context, step, run)
        await record_skill_uses(context, step, run, passed=True)
        await post_task_hooks(context, step, run)
        await absorb_step_result(context, step)
        next_transition(
            context, step, run, audit_browser_invocation=self._audit_browser_invocation
        )
