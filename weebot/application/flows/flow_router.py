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
from weebot.application.flows.state_graph import build_default_state_graph
from weebot.domain.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)


class FlowRouter:
    """Resolves the initial flow state based on session context and plan status."""

    # State name -> FlowState class mapping for StateGraph compatibility
    _state_class_map = {}
    _graph = None

    @classmethod
    def _get_graph(cls):
        """Lazily build the state graph (singleton per class)."""
        if cls._graph is None:
            from weebot.application.flows.states.executing import ExecutingState
            from weebot.application.flows.states.planning import PlanningState
            from weebot.application.flows.states.product_gate import ProductGateState

            cls._state_class_map = {
                "ExecutingState": ExecutingState,
                "PlanningState": PlanningState,
                "ProductGateState": ProductGateState,
            }
            cls._graph = build_default_state_graph()
        return cls._graph

    @staticmethod
    def _route_product_gate(
        session: Session, prompt: str, extra: dict | None = None
    ) -> tuple[str, Session]:
        """Route a session with a pending product-gate clarification.

        Extracted for use by :class:`~weebot.application.flows.state_graph.StateGraph`.
        Returns ``(state_name, updated_session)``.
        """
        extra_out = {**(extra or {}), "_product_gate_pending": False}
        updated = session.model_copy(
            update={"context": session.context.model_copy(update={"extra": extra_out})}
        )
        logger.info("Resuming product gate with user clarification")
        return ("ProductGateState", updated)

    @staticmethod
    def _route_plan_approval(
        session: Session, prompt: str, extra: dict | None = None
    ) -> tuple[str, Session]:
        """Route a session with a pending plan-approval decision.

        Extracted for use by :class:`~weebot.application.flows.state_graph.StateGraph`.
        Returns ``(state_name, updated_session)``.
        """
        from weebot.application.flows.states.plan_review import _APPROVE_TOKENS

        response = prompt.strip().lower()
        extra_out = {**(extra or {}), "plan_pending_approval": False}
        updated = session.model_copy(
            update={"context": session.context.model_copy(update={"extra": extra_out})}
        )

        if response in _APPROVE_TOKENS or not response:
            logger.info("Plan approved by user — proceeding to execution")
            updated = updated.set_status(SessionStatus.RUNNING)
            return ("ExecutingState", updated)

        logger.info("User requested plan modification: %r", prompt[:80])
        extra_out["_intent_reviewed"] = False
        extra_out["_plan_modification_request"] = prompt
        updated = session.model_copy(
            update={"context": session.context.model_copy(update={"extra": extra_out})}
        )
        return ("PlanningState", updated)

    @staticmethod
    def resolve_initial_state(
        session: Session, prompt: str, extra: dict | None = None
    ) -> tuple[FlowState, Session]:
        """Determine the initial flow state for a session.

        Priority:
        0. If product_gate_pending is set, route back to ProductGateState
           with the user's clarification.
        1. If plan_pending_approval is set, route based on user response.
        2. If an incomplete plan exists, resume execution.
        3. If the session was WAITING with a plan, resume execution.
        4. Otherwise, start fresh planning.

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
            return PlanningState(), updated

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
