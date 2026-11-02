"""Pre-execution gates for `ExecutingState` (WB-06, phase 4.1).

`ExecutingState.execute` was 509 lines and every one of these gates sat in the middle of
it, so the order they fire in was only visible by scrolling. Each gate is a *decision to
pause*: it either produces the event the caller should yield (and the run then returns) or
it leaves the prompt alone. Extracting them is what makes that order readable in
`execute`, and it is why `tests/unit/application/flows/test_executing_state_scripted.py`
exists first -- an extraction of untested ordering is a rewrite.

Order is behaviour, not preference:

  1. inbound mail   -- ADR 006: untrusted content fetched last step needs a human first
  2. constraint      -- a step that contradicts a stated constraint pauses before spending
  3. behavioural     -- learn from a correction before the step that might repeat it
  4. steering        -- a message typed during the run reaches THIS step (P3-2)
  5. repetition      -- a step that has run too often stops before calling a model
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from weebot.application.flows.states.base import StateId, new_state, task_text
from weebot.domain.models.event import AgentEvent, ErrorEvent

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.flows.states.executing import ExecutingState
    from weebot.domain.models.plan import Step

logger = logging.getLogger(__name__)

# Correction-learning is deduplicated per session per window: one user message is one
# correction, not one per step.
_BLEARN_DEDUP_WINDOW_S = 30.0


def mark_user_gate(session, gate: str):
    """Record that the flow is pausing on *gate* and awaiting a human answer.

    The flag lives in ``context.extra`` because that is the store
    ``SessionContext.get`` reads -- it checks declared fields and then
    ``extra``, and never ``context.facts``, where ``set_fact`` writes.
    ``FlowRouter.resolve_initial_state`` keys its routing off this, and a gate
    that does not set it is resumed by the branch that ignores the user's
    reply entirely.

    Lives here rather than on the state because every gate in this module sets it,
    and a state-to-collaborator import would be a cycle the cycle gate counts
    (lazy imports included).
    """
    new_extra = {**session.context.extra, "_user_gate_pending": gate}
    new_ctx = session.context.model_copy(update={"extra": new_extra})
    return session.model_copy(update={"context": new_ctx})


@dataclass
class GateOutcome:
    """What the caller should do after the gates ran.

    ``event`` set means: yield it and return. ``stop`` means: the state has already been
    changed, return without yielding. Both empty means: execute the step with
    ``effective_prompt``.
    """

    event: AgentEvent | None = None
    stop: bool = False
    effective_prompt: str = ""


async def apply_pre_step_gates(
    state: ExecutingState, context: PlanActFlow, step: Step, prompt: str
) -> GateOutcome:
    """Run the five gates in order and report the first one that fires.

    In AUTO execution mode every gate skips pausing — violations are logged
    but the step proceeds without user interaction.
    """
    pause = await _inbound_mail_gate(context)
    if pause is not None:
        return GateOutcome(event=pause, effective_prompt=prompt)

    pause = await _constraint_gate(state, context, step, prompt)
    if pause is not None:
        return GateOutcome(event=pause, effective_prompt=prompt)

    await _learn_from_correction(context, step, prompt)

    effective_prompt = await _steering_prompt(context, prompt)

    repetition = _repetition_gate(context, step)
    if repetition is not None:
        return GateOutcome(event=repetition, stop=True, effective_prompt=effective_prompt)

    return GateOutcome(effective_prompt=effective_prompt)


def _is_auto_mode(context: PlanActFlow) -> bool:
    """Return True when the flow is running in AUTO execution mode."""
    from weebot.domain.models.execution_mode import ExecutionMode

    mode = getattr(context, "_execution_mode", ExecutionMode.INTERACTIVE)
    return mode == ExecutionMode.AUTO


async def _inbound_mail_gate(context: PlanActFlow) -> AgentEvent | None:
    """ADR 006 / R1: content fetched from an inbox is untrusted, so acting on it is gated.

    In AUTO execution mode the gate clears the flag and logs the event but does
    not pause — the agent proceeds without human review.
    """
    if not context._session.get_fact("atomic_mail_inbound_pending"):
        return None

    from weebot.application.flows.collaborators.user_pause import pause_for_user
    from weebot.core.approval_policy import ExecApprovalPolicy

    policy = ExecApprovalPolicy().evaluate("act on inbound email content", "inbound_mail")
    if not policy.requires_confirmation:
        return None

    # Clear the flag — the mail arrived and we've noted it.
    context._session = context._session.set_fact("atomic_mail_inbound_pending", False)

    if _is_auto_mode(context):
        logger.info(
            "AUTO mode: inbound mail gate skipped — agent may act on %s without review",
            context._session.id,
        )
        return None

    context._session = mark_user_gate(context._session, "inbound_mail")
    return await pause_for_user(
        context,
        "The previous step retrieved content from an @atomicmail.ai inbox.\n"
        "Inbound email is untrusted input — acting on it without review "
        "is a security risk (ADR 006).\n\n"
        "Review the retrieved content above, then type 'proceed' to "
        "continue, or describe how you'd like to handle it.",
    )


async def _constraint_gate(
    state: ExecutingState, context: PlanActFlow, step: Step, prompt: str
) -> AgentEvent | None:
    """Lost-in-Compaction Phase 5.4: pause before a step that contradicts a constraint.

    In AUTO execution mode the violation is logged and acknowledged but the step
    proceeds without pausing.
    """
    from weebot.application.flows.collaborators.user_pause import pause_for_user

    ack_key = f"constraint_gate_ack:{step.id}"
    violations = (
        []
        if context._session.get_fact(ack_key)
        else state._constraint_violations(context, step, task_text(context, prompt))
    )
    if not violations:
        return None

    violation_text = "; ".join(c.text for c in violations[:2])

    # Always journal and acknowledge, regardless of mode.
    await state._journal_constraint_violation(context, step, violations[0].text)
    context._session = context._session.set_fact(ack_key, True)

    if _is_auto_mode(context):
        logger.warning(
            "AUTO mode: constraint gate skipped — step '%s' may violate: %s",
            step.id,
            violation_text,
        )
        return None

    logger.warning(
        "Step '%s' may violate constraint: %s — pausing for user", step.id, violation_text
    )
    context._session = mark_user_gate(context._session, "constraint")
    return await pause_for_user(
        context,
        f"Step '{step.description}' may violate a stated constraint:\n"
        f"  {violation_text}\n\n"
        f"Type 'proceed' to allow this step, or describe an alternative approach.",
    )


async def _learn_from_correction(context: PlanActFlow, step: Step, prompt: str) -> None:
    """Capability 5: extract a behavioural rule from a user correction, at most once per
    session per window."""
    if context._behavioral_learner is None or not prompt:
        return

    import time as _time

    now = _time.monotonic()
    last = getattr(context, "_last_blearn_ts", {}).get(context._session.id, 0)
    if now - last <= _BLEARN_DEDUP_WINDOW_S:
        return

    try:
        await context._behavioral_learner.learn_from_correction(
            prompt,
            {
                "session_id": context._session.id,
                "step_description": step.description if step else "",
                "tool_name": "",
            },
        )
    except Exception as ble:
        logger.warning("Behavioral learner error: %s", ble)

    if not hasattr(context, "_last_blearn_ts"):
        context._last_blearn_ts = {}
    context._last_blearn_ts[context._session.id] = now


async def _steering_prompt(context: PlanActFlow, prompt: str) -> str:
    """Phase 5: fold a mid-run user message into this step's prompt."""
    if context._steering is None:
        return prompt

    steering_msg = await context._steering.poll(context._session.id)
    if not steering_msg:
        return prompt

    logger.info(
        "Steering received for session %s: %s", context._session.id, steering_msg[:80]
    )
    return (
        f"{prompt}\n\n[STEERING — the user says: {steering_msg}. "
        "Adjust your approach immediately.]"
    )


def _repetition_gate(context: PlanActFlow, step: Step) -> AgentEvent | None:
    """Count this attempt and stop a step that keeps coming back."""
    count = context._step_execution_counts.get(step.id, 0) + 1
    context._step_execution_counts[step.id] = count
    if count <= context._max_step_repetitions:
        return None

    logger.warning(
        "Step %s executed %d times (limit: %d). Forcing completion.",
        step.id,
        count,
        context._max_step_repetitions,
    )
    context.set_state(new_state(StateId.VERIFYING))
    return ErrorEvent(
        error=f"Step '{step.description}' repeated {count} times. "
        f"Agent may be stuck in a loop. Completing task."
    )
