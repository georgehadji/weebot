"""delete_session — stop a session's run, then remove it from every store (audit R04).

The order is the point: the flow's next save is an upsert, so deleting while it still
runs brings the session back, and it keeps running after the user was told it was gone.
Runs owned by a gateway or the webhook route are not TaskRunner tasks and cannot be
cancelled here; the log says so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.ports.task_runner_port import TaskRunnerPort
    from weebot.application.services.session_deletion_orchestrator import (
        SessionDeletionOrchestrator,
    )

logger = logging.getLogger(__name__)


@dataclass
class DeleteSession:
    task_runner: TaskRunnerPort | None
    orchestrator: SessionDeletionOrchestrator

    async def execute(self, session_id: str) -> dict[str, str]:
        if self.task_runner is not None and await self.task_runner.cancel_session(session_id):
            logger.info("Stopped session %s before deleting it", session_id)
        else:
            logger.debug("No TaskRunner run to stop for session %s", session_id)
        results = await self.orchestrator.delete_session(session_id)
        # The per-session security caches are not a store, but they are keyed by this
        # session id and would otherwise outlive it in this process (WB-03).
        from weebot.application.agents.executor._session_scope import get_session_scope

        get_session_scope().close(session_id)
        return results
