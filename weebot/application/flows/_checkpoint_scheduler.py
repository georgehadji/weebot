"""Checkpoint scheduler for PlanActFlow — save after each step, restore on recovery."""

from __future__ import annotations

import logging
from typing import Any

from weebot.domain.models.checkpoint import FlowCheckpoint, StepCheckpoint
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, StepStatus
from weebot.domain.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)


def _state_name(state: Any) -> str:
    """The state's StateId value ("executing"), which FlowCheckpoint documents."""
    from weebot.application.flows.states.base import _STATES

    for state_id, cls in _STATES.items():
        if type(state) is cls:
            return state_id.value
    return type(state).__name__ if state is not None else ""


def _completed(plan: Plan) -> int:
    return sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED)


class CheckpointScheduler:
    """Save a FlowCheckpoint after each step, so an interrupted flow can resume."""

    def __init__(self, checkpoint_port: Any | None = None):
        self._checkpoint_port = checkpoint_port

    async def maybe_save(self, session: Session, plan: Plan | None, state: Any) -> None:
        """Save a checkpoint if the port is wired; a failed save is logged, never raised."""
        if self._checkpoint_port is None or plan is None:
            return

        try:
            completed = [
                StepCheckpoint(
                    step_id=step.id,
                    description=step.description,
                    status=step.status.value,
                    result=step.result,
                )
                for step in plan.steps
                if step.status.value in ("completed", "failed")
            ]
            summary = "\n".join(
                f"{c.step_id}: {(c.result or c.status)[:200]}" for c in completed[-3:]
            )
            checkpoint = FlowCheckpoint(
                session_id=session.id,
                flow_type="PlanActFlow",
                current_state=_state_name(state),
                plan_snapshot=plan,
                completed_steps=completed,
                conversation_summary=summary,
            )
            await self._checkpoint_port.save(checkpoint)
            logger.debug("Checkpoint saved for session %s", session.id)
        except Exception:
            logger.warning("Failed to save checkpoint for session %s", session.id, exc_info=True)


def restore_from_checkpoint(session: Session, checkpoint: FlowCheckpoint) -> Session:
    """Put the checkpointed plan back into *session* when its own copy fell behind.

    The session is left WAITING, which is what a resume expects: FlowRouter then
    finds the incomplete plan and goes straight to execution.
    """
    own = session.get_last_plan()
    if own is None or _completed(own) < _completed(checkpoint.plan_snapshot):
        session = session.add_event(
            PlanEvent(status=PlanStatus.RUNNING, plan=checkpoint.plan_snapshot.model_dump())
        )
    return session.set_status(SessionStatus.WAITING)
