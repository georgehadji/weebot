"""Checkpoint scheduler for PlanActFlow — decoupled save logic."""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.domain.models.checkpoint import FlowCheckpoint, StepCheckpoint
from weebot.domain.models.plan import Plan
from weebot.domain.models.session import Session

logger = logging.getLogger(__name__)


class CheckpointScheduler:
    """Encapsulates flow checkpoint save logic.

    Called after each step event so that a crashed flow can resume
    from the last completed step.
    """

    def __init__(self, checkpoint_port: Optional[Any] = None):
        self._checkpoint_port = checkpoint_port

    async def maybe_save(
        self,
        session: Session,
        plan: Plan,
        current_state_name: str,
    ) -> None:
        """Save a checkpoint if the port is wired.

        Args:
            session: The current flow session.
            plan: The current plan snapshot.
            current_state_name: The name of the current flow state
                (e.g. ``"PlanningState"``).
        """
        if self._checkpoint_port is None or plan is None:
            return

        try:
            completed: list[StepCheckpoint] = []
            for step in plan.steps:
                if step.status.value in ("completed", "failed"):
                    completed.append(
                        StepCheckpoint(
                            step_id=step.id,
                            description=step.description,
                            status=step.status.value,
                            result=step.result,
                        )
                    )

            checkpoint = FlowCheckpoint(
                session_id=session.id,
                flow_type="PlanActFlow",
                current_state=current_state_name,
                plan_snapshot=plan,
                completed_steps=completed,
                conversation_summary="",
                iteration_count=0,
            )
            await self._checkpoint_port.save(checkpoint)
            logger.debug("Checkpoint saved for session %s", session.id)
        except Exception:
            logger.warning(
                "Failed to save checkpoint for session %s", session.id, exc_info=True,
            )
