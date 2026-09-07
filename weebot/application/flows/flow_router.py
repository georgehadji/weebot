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

from weebot.application.flows.states.base import FlowState
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.planning import PlanningState
from weebot.domain.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)


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
            if response in _APPROVE_TOKENS:
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

        return PlanningState(), session

    @staticmethod
    async def record_misalignment(session: Session, prompt: str, journal: Any = None) -> None:
        """Record a user correction in the misalignment journal (best-effort)."""
        if journal is None:
            return
        try:
            import asyncio
            from weebot.domain.models.misalignment_entry import MisalignmentEntry

            asyncio.ensure_future(
                journal.record(
                    MisalignmentEntry(
                        session_id=session.id,
                        project_path=session.context.get("working_dir", ""),
                        symptom="user_correction",
                        correction_text=prompt[:500],
                    )
                )
            )
        except ImportError:
            pass
