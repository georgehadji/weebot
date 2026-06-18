"""FlowRouter — resolves initial flow state from session context.

Extracted from PlanActFlow.run() to reduce coupling and make state
routing testable in isolation.  Determines whether a session should
resume, re-plan, or enter plan-review approval.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.application.flows.states.base import FlowState
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.planning import PlanningState
from weebot.domain.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)


class FlowRouter:
    """Resolves the initial flow state based on session context and plan status."""

    @staticmethod
    def check_plan_pending_approval(session: Session, prompt: str) -> Optional[FlowState]:
        """Check for plan_pending_approval flag and route accordingly.

        Returns a FlowState if the flag was handled, None otherwise.
        """
        if not session.context.get("plan_pending_approval"):
            return None

        from weebot.application.flows.states.plan_review import _APPROVE_TOKENS

        response = prompt.strip().lower()
        if response in _APPROVE_TOKENS or not response:
            logger.info("Plan approved by user — proceeding to execution")
            return ExecutingState()

        logger.info("User requested plan modification: %r", prompt[:80])
        return PlanningState()

    @staticmethod
    async def record_misalignment(
        session: Session,
        prompt: str,
        journal: Any = None,
    ) -> None:
        """Record a user correction in the misalignment journal (best-effort)."""
        if journal is None:
            return
        try:
            import asyncio
            from weebot.domain.models.misalignment_entry import MisalignmentEntry
            asyncio.ensure_future(journal.record(
                MisalignmentEntry(
                    session_id=session.id,
                    project_path=session.context.get("working_dir", ""),
                    symptom="user_correction",
                    correction_text=prompt[:500],
                )
            ))
        except ImportError:
            pass

    @staticmethod
    def resolve_initial_state(
        session: Session,
        prompt: str,
        plan_pending_approval: bool = False,
    ) -> FlowState:
        """Determine the initial flow state for a session.

        Priority:
        1. If plan_pending_approval is set, route based on user response.
        2. If an incomplete plan exists, resume execution.
        3. If the session was WAITING with a plan, resume execution.
        4. Otherwise, start fresh planning.
        """
        last_plan = session.get_last_plan()

        if plan_pending_approval:
            state = FlowRouter.check_plan_pending_approval(session, prompt)
            if state is not None:
                return state

        if last_plan is not None and not last_plan.is_complete():
            logger.info("Resuming session %s with existing plan", session.id)
            return ExecutingState()

        if session.status == SessionStatus.WAITING and last_plan is not None:
            logger.info("Session %s was waiting, resuming execution", session.id)
            return ExecutingState()

        return PlanningState()
