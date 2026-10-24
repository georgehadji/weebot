"""FlowRouter — resolves initial flow state from session context.

Extracted from PlanActFlow.run() to reduce coupling and make state
routing testable in isolation.  Determines whether a session should
resume, re-plan, enter product-gate clarification, or plan-review
approval.

Returns both the resolved FlowState and a (possibly mutated) Session,
so callers can apply context mutations alongside the transition.
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.domain.services.session_lessons import project_key
from weebot.application.flows.states.base import FlowState
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.planning import PlanningState
from weebot.domain.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)


def _apply_plan_file(session: Session) -> Session:
    """If the user edited Output/<session>/01_plan.md, the edited steps are the
    plan (ICM B2). Unchanged steps keep their ids; an untouched file changes nothing."""
    from weebot.core import plan_file
    from weebot.domain.models.event import PlanEvent
    from weebot.domain.models.plan import PlanStatus, Step

    plan = session.get_last_plan()
    edited = plan_file.read_steps(session.id) if plan is not None else None
    if not edited or edited == [s.description for s in plan.steps]:
        return session
    by_text = {s.description: s for s in plan.steps}
    steps = [by_text.get(d) or Step(id=f"edited-{i}", description=d) for i, d in enumerate(edited, 1)]
    logger.info("Plan file edited by the user: %d -> %d steps", len(plan.steps), len(steps))
    new_plan = plan.model_copy(update={"steps": steps})
    return session.add_event(
        PlanEvent(status=PlanStatus.UPDATED, plan=new_plan.model_dump(mode="json"))
    )


class FlowRouter:
    """Resolves the initial flow state based on session context and plan status."""

    @staticmethod
    def resolve_initial_state(
        session: Session, prompt: str, extra: dict | None = None
    ) -> tuple[FlowState, Session]:
        """Determine the initial flow state for a session.

        Priority:
        0. If product_gate_pending is set, route back to ProductGateState
           with the user's clarification.
        1. If plan_pending_approval is set, route based on user response.
        2. If _user_gate_pending is set, route based on user response.
        3. If an incomplete plan exists, resume execution.
        4. If the session was WAITING with a plan, resume execution.
        5. Otherwise, start fresh planning.

        Returns:
            (FlowState, Session) — the state to transition to, and the
            (possibly mutated) session with context flags updated.
        """
        # Priority 0: Product gate clarification pending
        product_gate_pending = session.context.get("_product_gate_pending")
        if product_gate_pending:
            from weebot.application.flows.states.product_gate import ProductGateState

            # Clear the pending flag
            extra_out = {**(extra or {}), "_product_gate_pending": False}
            updated = session.model_copy(
                update={"context": session.context.model_copy(update={"extra": extra_out})}
            )
            logger.info("Resuming product gate with user clarification")
            return ProductGateState(resume_with=prompt), updated

        plan_pending_approval = session.context.get("plan_pending_approval")

        if plan_pending_approval:
            from weebot.application.flows.states.plan_review import _APPROVE_TOKENS

            response = prompt.strip().lower()

            # Clear the approval flag regardless of outcome
            extra_out = {**(extra or {}), "plan_pending_approval": False}
            updated = session.model_copy(
                update={"context": session.context.model_copy(update={"extra": extra_out})}
            )

            if response in _APPROVE_TOKENS or not response:
                logger.info("Plan approved by user — proceeding to execution")
                updated = _apply_plan_file(updated)
                # Transition from WAITING → RUNNING so the main loop
                # doesn't break prematurely (it breaks on WAITING).
                updated = updated.set_status(SessionStatus.RUNNING)
                return ExecutingState(), updated

            logger.info("User requested plan modification: %r", prompt[:80])
            # Set modification context so PlanningState re-runs
            extra_out["_intent_reviewed"] = False
            extra_out["_plan_modification_request"] = prompt
            updated = session.model_copy(
                update={"context": session.context.model_copy(update={"extra": extra_out})}
            )
            # RUNNING for the same reason the approve branch above states: the
            # run loop breaks on WAITING (plan_act_flow.py), and PlanReviewState
            # leaves the session WAITING before it pauses. Without this, asking
            # for a plan change re-planned once and then halted -- the user saw
            # a new plan and nothing after it.
            return PlanningState(), updated.set_status(SessionStatus.RUNNING)

        # Priority 2: a gate asked the human a question and is awaiting the answer.
        #
        # Without this, the resume fell through to the branch below, which
        # returns ExecutingState without reading `prompt` at all. Both gates
        # that set this flag ask the user to approve *or* to say how they want
        # the content handled, and neither half was honoured: the description
        # was discarded, and no answer declined. For the inbound-mail gate that
        # meant untrusted email was acted on identically whatever the human
        # typed, which is the one thing ADR 006 exists to prevent.
        user_gate = session.context.get("_user_gate_pending")
        if user_gate:
            from weebot.application.flows.states.plan_review import _APPROVE_TOKENS

            response = prompt.strip().lower()
            # Merge onto the session's own extra rather than replacing it with
            # the caller's. The two branches above spell this `{**(extra or
            # {}), ...}`, which erases every other key when a caller omits the
            # kwarg -- latent only because the one production caller passes it.
            extra_out = {**session.context.extra, **(extra or {}), "_user_gate_pending": None}

            # An empty answer is deliberately NOT approval here, though the
            # plan-approval path above accepts it as one. These gates guard
            # untrusted input and stated constraints: silence is not consent.
            approved = response in _APPROVE_TOKENS
            if user_gate == "tool_approval":
                # ADR-013: "yes" becomes a single-use grant for the exact call
                # the step paused on, which the re-run step then consumes;
                # "always" also allowlists a first-time egress host.
                from weebot.application.services.tool_approval import record_flow_reply

                pending = session.context.get("_tool_approval_pending") or {}
                approved = record_flow_reply(
                    session.id, pending, prompt, approve_tokens=_APPROVE_TOKENS
                )
                extra_out["_tool_approval_pending"] = None
            if approved:
                logger.info("User approved the %s gate — resuming execution", user_gate)
                # Clear the flag and fall through to the ordinary resume logic
                # below rather than returning ExecutingState here. Approval
                # means "carry on as before", and the branches below already
                # know what "as before" is -- they check that a plan exists and
                # is incomplete first. Short-circuiting would resume execution
                # for a session with no plan to execute, a state the router
                # could not previously produce.
                session = session.model_copy(
                    update={"context": session.context.model_copy(update={"extra": extra_out})}
                )
            else:
                logger.info(
                    "User did not approve the %s gate (%r) — re-planning with their instruction",
                    user_gate,
                    prompt[:80],
                )
                extra_out["_intent_reviewed"] = False
                extra_out["_plan_modification_request"] = prompt
                updated = session.model_copy(
                    update={"context": session.context.model_copy(update={"extra": extra_out})}
                )
                # The plan that tripped the gate is being discarded, so the
                # per-step acks recorded against it must not survive into its
                # replacement. Step ids are positional (`step-N`, planner.py),
                # so a re-planned step-3 would inherit the old step-3's ack and
                # skip the very gate the user just refused.
                for key in list(updated.context.facts):
                    if key.startswith("constraint_gate_ack:"):
                        updated = updated.set_fact(key, False)
                # Declining must not disarm the mail gate either. The fetched
                # message is still in the transcript and is about to be handed
                # to the planner, so whatever the new plan does with it has to
                # be gated again. The gate cleared this flag before pausing,
                # which is right for approval and wrong for a refusal.
                if user_gate == "inbound_mail":
                    updated = updated.set_fact("atomic_mail_inbound_pending", True)
                # RUNNING, for the same reason the approve branch of Priority 1
                # says: the run loop breaks on WAITING. Returning PlanningState
                # while still WAITING re-plans once and then halts, so the user
                # gets a new plan and silence. Priority 1's own decline branch
                # has this defect too and is fixed with it, just below.
                return PlanningState(), updated.set_status(SessionStatus.RUNNING)

        last_plan = session.get_last_plan()

        if last_plan is not None and not last_plan.is_complete():
            logger.info("Resuming session %s with existing plan", session.id)
            if session.status == SessionStatus.WAITING:
                session = session.set_status(SessionStatus.RUNNING)
            return ExecutingState(), session

        if session.status == SessionStatus.WAITING and last_plan is not None:
            logger.info("Session %s was waiting, resuming execution", session.id)
            session = session.set_status(SessionStatus.RUNNING)
            return ExecutingState(), session

        # WAITING with no plan: the answer to a pre-plan question (intent
        # review). Still WAITING, the run loop breaks right after planning.
        if session.status == SessionStatus.WAITING:
            session = session.set_status(SessionStatus.RUNNING)
        return PlanningState(), session

    @staticmethod
    async def record_misalignment(session: Session, prompt: str, journal: Any = None) -> None:
        """Record a user correction in the misalignment journal (best-effort)."""
        if journal is None:
            return
        try:
            from weebot.core.background_tasks import get_background_tasks
            from weebot.domain.models.misalignment_entry import MisalignmentEntry

            get_background_tasks().spawn(
                journal.record(
                    MisalignmentEntry(
                        session_id=session.id,
                        project_path=project_key(session.context.get("working_dir")),
                        symptom="user_correction",
                        correction_text=prompt[:500],
                    )
                ),
                name="misalignment-journal",
            )
        except ImportError:
            pass
