"""What happens after a step ran: routing, gates, completion, transition (WB-06, 4.1).

Split out of `ExecutingState.execute` (509 lines). Everything here runs after the mediator
returned, and every branch ends in exactly one `context.set_state(...)`, so the whole
state machine's post-step vocabulary is in one file:

  failure            -> retry once (minor), replan (critical), or update (otherwise)
  quality gates      -> retry with a hint, or move on, but never silently
  completion         -> step COMPLETED, hooks, knowledge graph
  transition         -> verifying, reviewing, or the next step

`execute` keeps the ordering; this module keeps the decisions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from weebot.application.flows.states.base import StateId, new_state
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.plan import Step, StepStatus
from weebot.domain.models.session import SessionStatus

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.flows.states._step_run import StepRun

logger = logging.getLogger(__name__)

# ── Code step detection (Phase 8: per-step code review) ──────────────────────
# Tool names whose presence indicates a code-producing step
_CODE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "file_editor",
        "edit_file",
        "write_file",
        "create_file",
        "bash",
        "shell",
        "execute_command",
        "run_command",
        "write",
        "edit",
        "patch",
    }
)

# Step description keywords that indicate code production
_CODE_KEYWORDS: frozenset[str] = frozenset(
    {
        "implement",
        "write",
        "create file",
        "edit file",
        "modify",
        "add function",
        "add method",
        "add class",
        "fix bug",
        "refactor",
        "update file",
        "generate",
        "scaffold",
        "build",
        "code",
        "script",
        "patch",
    }
)

# Reviewer retries gate — must match _MAX_REVIEW_RETRIES in ReviewingState
MAX_REVIEW_RETRIES_GATE: int = 2

# Replans in a row with no step completed in between. Each replan swaps in a step with a
# new id, so the per-step repetition limit never sees them (de5d0990: six replans of one
# unexplained error, ended only by the token budget).
MAX_REPLANS_WITHOUT_PROGRESS: int = 3


def is_code_step(step: Step, events: list[Any] | None = None) -> bool:
    """Return True if this step likely produced or modified code.

    Uses both keyword matching on the step description and, when available,
    tool-name inspection from captured execution events.
    """
    desc_lower = step.description.lower()
    if any(kw in desc_lower for kw in _CODE_KEYWORDS):
        return True
    if events:
        for e in events:
            if isinstance(e, dict):
                if e.get("tool_name", "") in _CODE_TOOL_NAMES:
                    return True
    return False


async def route_failure(context: PlanActFlow, step: Step, run: StepRun) -> ErrorEvent | None:
    """Three-tier failure routing. Always sets a state; never completes the step.

    Returns an error for the user when the run stops instead of replanning.
    """
    if await _all_models_tripped(context, step, run):
        return None

    error_msg = _error_message(run)

    from weebot.application.agents.executor._error_handler import classify_failure_severity

    severity = classify_failure_severity(error_msg)
    if severity == "minor_fix" and step.retry_count < 1:
        logger.warning("Step %s MINOR failure (%s) — retrying once", step.id, severity)
        # Reset step to PENDING so get_next_step() picks it up again
        retried = step.model_copy(
            update={"status": StepStatus.PENDING, "retry_count": step.retry_count + 1}
        )
        context._plan = context._plan.replace_step(step.id, retried)
        context.set_state(new_state(StateId.EXECUTING))
        return None

    replans = getattr(context, "_replans_without_progress", 0) + 1
    context._replans_without_progress = replans
    if replans > MAX_REPLANS_WITHOUT_PROGRESS:
        logger.warning(
            "Step %s failed after %d replans without progress; stopping", step.id, replans - 1
        )
        reason = (
            f"Stopped: the plan was replanned {replans - 1} times in a row and no step "
            f"completed. Last error: {error_msg[:300]}"
        )
        context._plan = context._plan.update_step_status(step.id, StepStatus.FAILED, result=reason)
        context.set_state(new_state(StateId.VERIFYING))
        return ErrorEvent(error=reason)

    if severity == "full_replan":
        logger.warning(
            "Step %s CRITICAL failure (%s) — restarting planning", step.id, severity
        )
        context.set_state(new_state(StateId.PLANNING))
    else:
        logger.warning(
            "Step %s failed during execution in %.1fs (%s); transitioning to UPDATING",
            step.id,
            run.elapsed_s,
            severity,
        )
        context.set_state(new_state(StateId.UPDATING))
    return None


async def _all_models_tripped(context: PlanActFlow, step: Step, run: StepRun) -> bool:
    """If every model is circuit-broken, replanning would fail too: mark UNVERIFIED.

    Reads the reconstructed events, not the raw dicts: `getattr(e, "error", "")` on a
    dict returns "" for every entry, which is how this branch was dead until
    test_executing_state_scripted.py asked it a question.
    """
    tripped = any(
        isinstance(ev, ErrorEvent)
        and "All models in the cascade have tripped" in str(ev.error or "")
        for ev in run.events
    )
    if not tripped:
        return False

    logger.warning(
        "Step %s: all models tripped — skipping replan, marking UNVERIFIED (%.1fs)",
        step.id,
        run.elapsed_s,
    )
    # Not COMPLETED: no model was able to run, so there is no evidence a real audit could
    # check. Forcing completion here would be exactly the silent bypass E1 exists to close.
    context._plan = context._plan.update_step_status(
        step.id,
        StepStatus.UNVERIFIED,
        result="all models circuit-broken — step did not execute",
    )
    context.set_state(new_state(StateId.VERIFYING))
    return True


def _error_message(run: StepRun) -> str:
    """The actual error text from the step's events.

    `_current_step_events`, not the raw dicts: an isinstance check never matches a dict,
    so every failure read as "step execution failed" and the routing above was dead.
    """
    for event in run.events:
        if isinstance(event, ErrorEvent):
            return str(event.error or "step execution failed")
    return "step execution failed"


def quality_gate(context: PlanActFlow, step: Step, run: StepRun) -> bool:
    """Phase 3 step-result quality check. Returns True when it forced a retry."""
    enabled = getattr(getattr(context, "_task_preset", None), "enable_step_validation", True)
    if not enabled or step.retry_count >= 1:
        return False

    from weebot.application.services.step_result_validator import StepResultValidator

    validation = StepResultValidator().validate(
        result=str(run.result_text or ""),
        step_description=step.description,
        previous_result=None,
        step_events=run.events,
    )
    if validation.passed:
        return False

    logger.info(
        "Step '%s' failed quality check (%s) — retrying with hint",
        step.id,
        validation.reason,
    )
    # Inject the quality hint into the step description and retry it once.
    hint_step = step.model_copy(
        update={
            "description": f"{step.description}\n[Quality hint: {validation.quality_hint}]",
            "retry_count": 1,
            "status": StepStatus.PENDING,
        }
    )
    context._plan = context._plan.replace_step(step.id, hint_step)
    context.set_state(new_state(StateId.EXECUTING))
    return True


async def progress_gate(context: PlanActFlow, step: Step, run: StepRun) -> bool:
    """Improvement 6: per-step progress evaluation. Returns True when it stopped the step."""
    evaluator = getattr(context, "_step_evaluator", None)
    if evaluator is None or not run.result_text:
        return False

    previous_outputs = [
        s.result for s in context._plan.steps if s.is_done() and s.id != step.id and s.result
    ]
    evaluation = await evaluator.evaluate(
        step=step,
        output=str(run.result_text),
        plan=context._plan,
        previous_outputs=previous_outputs,
    )
    if evaluation.evaluator_failed:
        # Fail-open by policy: the step proceeds. But it proceeds UNVERIFIED, and that
        # used to be invisible here -- the only log was on `not passed`, and a failed
        # evaluator returns passed=True. An outage silently disabled the progress gate
        # for every step and nothing said so.
        logger.warning(
            "Step '%s' was NOT evaluated (%s) — progress gate skipped, "
            "step allowed through by fail-open policy.",
            step.id,
            evaluation.reasoning,
        )
        return False

    if evaluation.passed:
        return False

    logger.warning(
        "Step '%s' failed progress eval (score=%.2f, regression=%s): %s",
        step.id,
        evaluation.score,
        evaluation.regression_detected,
        evaluation.reasoning,
    )
    context.set_state(new_state(StateId.UPDATING))
    return True


def complete_step(context: PlanActFlow, step: Step, run: StepRun) -> None:
    """Commit the step as COMPLETED, carrying its result."""
    context._replans_without_progress = 0
    context._plan = context._plan.update_step_status(
        step.id, StepStatus.COMPLETED, result=run.result_text or None
    )
    logger.info("Step %s completed in %.1fs", step.id, run.elapsed_s)


async def post_task_hooks(context: PlanActFlow, step: Step, run: StepRun) -> None:
    """Fire `post_task` for observers tracking step timing (pause and completion paths)."""
    if getattr(context, "_hooks", None) is None:
        return
    await context._hooks.execute_hooks(
        "post_task",
        {
            "session_id": context._session.id,
            "step_id": step.id,
            "step_description": step.description,
            "elapsed_ms": run.elapsed_s * 1000,
            "plan": context._plan,
        },
    )


async def pre_task_hooks(context: PlanActFlow, step: Step) -> None:
    """Fire `pre_task` before the step runs."""
    if getattr(context, "_hooks", None) is None:
        return
    step_index = next((i for i, s in enumerate(context._plan.steps) if s.id == step.id), 0)
    await context._hooks.execute_hooks(
        "pre_task",
        {
            "session_id": context._session.id,
            "step_id": step.id,
            "step_description": step.description,
            "step_index": step_index,
            "total_steps": len(context._plan.steps),
            "plan": context._plan,
        },
    )


async def error_hooks(context: PlanActFlow, step: Step) -> None:
    """Fire `on_error` for a failed step."""
    if getattr(context, "_hooks", None) is None:
        return
    await context._hooks.execute_hooks(
        "on_error",
        {
            "session_id": context._session.id,
            "step_id": step.id,
            "error": "step execution failed",
            "error_type": "step_failure",
            "plan": context._plan,
        },
    )


async def absorb_step_result(context: PlanActFlow, step: Step) -> None:
    """Capability 2: upsert facts the step discovered into the knowledge graph."""
    if context._knowledge_graph is None:
        return
    try:
        await context._knowledge_graph.extract_from_step_result(
            step_description=step.description,
            result=step.result or "",
            session_id=context._session.id,
        )
    except Exception as kg_exc:
        logger.warning("Knowledge graph extraction failed: %s", kg_exc)


def next_transition(
    context: PlanActFlow, step: Step, run: StepRun, *, audit_browser_invocation
) -> None:
    """Pick the successor state after a completed step.

    terminate -> verifying if nothing is pending, else stay for the next step
    plan done -> verifying (with the browser-invocation audit)
    code step -> reviewing (when a reviewer is configured and retries remain)
    otherwise -> executing the next step
    """
    if run.should_terminate:
        logger.info("Terminate detected for step %s", step.id)
        if context._plan.get_next_step() is not None:
            logger.info(
                "Continuing to next step: %s (%d pending remaining)",
                context._plan.get_next_step().id,
                len(context._plan.get_pending_steps()),
            )
            # Don't transition -- the loop in run() re-enters ExecutingState, which asks
            # get_next_step() again.
        else:
            logger.info("All steps complete after terminate — verifying")
            context.set_state(new_state(StateId.VERIFYING))
        return

    if context._auto_terminate_on_plan_complete and context._plan.is_complete():
        audit_browser_invocation(context)
        logger.info("All plan steps completed. Auto-terminating.")
        context.set_state(new_state(StateId.VERIFYING))
        return

    # Compact memory after each step
    context._session = context._compactor.compact_session(context._session)

    if context._plan.get_next_step() is None:
        context.set_state(new_state(StateId.VERIFYING))
        return

    if (
        getattr(context, "_code_reviewer", None) is not None
        and is_code_step(step, events=run.events)
        and step.retry_count < MAX_REVIEW_RETRIES_GATE
    ):
        context.set_state(
            new_state(
                StateId.REVIEWING,
                step=step,
                reviewer=context._code_reviewer,
                step_events=list(run.events),
            )
        )
    else:
        context.set_state(new_state(StateId.EXECUTING))


def pause_for_human(context: PlanActFlow) -> None:
    """A step that produced a human-in-the-loop event leaves the session WAITING."""
    context._session = context._session.set_status(SessionStatus.WAITING)
