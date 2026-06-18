"""CancelSessionHandler — handles CancelSession command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.services.task_runner import TaskRunner

from weebot.application.cqrs.commands import CancelSessionCommand

from weebot.domain.models.session import SessionStatus

class CancelSessionHandler(CommandHandler):
    """Cancel a running session via the TaskRunner."""

    def __init__(self, task_runner: TaskRunner):
        self._task_runner = task_runner

    async def handle(self, command: CancelSessionCommand) -> CommandResult:
        try:
            success = await self._task_runner.cancel_session(command.session_id)
            if success:
                return CommandResult.ok(
                    data={
                        "session_id": command.session_id,
                        "cancelled": True,
                        "reason": command.reason,
                    }
                )
            return CommandResult.fail(
                error=f"Session {command.session_id} not found or not active",
                error_code="SESSION_NOT_ACTIVE",
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="CANCEL_ERROR"
            )

