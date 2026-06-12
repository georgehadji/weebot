"""FlowPersistence — extracted from PlanActFlow for session persistence concerns."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from weebot.application.ports.checkpoint_port import CheckpointPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.domain.models.plan import Plan
    from weebot.domain.models.session import Session
    from weebot.core.structured_logger import StructuredLogger

logger = logging.getLogger(__name__)


class FlowPersistence:
    """Manages session persistence, checkpoints, and event-level durability."""

    def __init__(
        self,
        state_repo: Optional["StateRepositoryPort"] = None,
        checkpoint_port: Optional["CheckpointPort"] = None,
        logger_obj: Optional["StructuredLogger"] = None,
    ):
        self._state_repo = state_repo
        self._checkpoint_port = checkpoint_port
        self._log = logger_obj or logger
        self._emit_lock = asyncio.Lock()
        self._persistence_adapter = None

    async def save_session(self, session: "Session") -> bool:
        """Persist session to state repository.

        Returns True on success, False on failure.
        """
        if not self._state_repo:
            return True

        async with self._emit_lock:
            adapter = self._get_persistence_adapter()
            if adapter is not None:
                ok = await adapter.save_session(session)
                if not ok:
                    self._log.error(
                        "Session %s dead-lettered — persistence exhausted retries",
                        session.id,
                    )
                    return False
            else:
                try:
                    await self._state_repo.save_session(session)
                except Exception as exc:
                    self._log.warning("Session persistence failed (retryable): %s", exc)
                    return False
        return True

    async def save_checkpoint(self, session: "Session", plan: Optional["Plan"], state_name: str) -> bool:
        """Save a flow checkpoint.

        Returns True on success, False if checkpoint_port is not available or fails.
        """
        if self._checkpoint_port is None or plan is None:
            return False

        try:
            from weebot.domain.models.checkpoint import FlowCheckpoint, StepCheckpoint
            completed = [
                StepCheckpoint(
                    step_id=s.id, description=s.description,
                    status=s.status.value, result=s.result,
                )
                for s in plan.steps if s.status.value in ("completed", "failed")
            ]
            checkpoint = FlowCheckpoint(
                session_id=session.id,
                flow_type="PlanActFlow",
                current_state=state_name,
                plan_snapshot=plan,
                completed_steps=completed,
                conversation_summary="",
                iteration_count=0,
            )
            await self._checkpoint_port.save(checkpoint)
            return True
        except Exception:
            self._log.warning("Failed to save checkpoint for session %s", session.id, exc_info=True)
            return False

    def _get_persistence_adapter(self):
        """Lazy-resolve session persistence adapter from DI container."""
        if self._persistence_adapter is None:
            try:
                from weebot.application.di import Container
                c = Container()
                c.configure_defaults()
                self._persistence_adapter = c.get("session_persistence")
            except (KeyError, Exception):
                return None
        return self._persistence_adapter
