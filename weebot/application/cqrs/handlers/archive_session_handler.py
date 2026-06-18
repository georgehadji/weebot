"""ArchiveSessionHandler — handles ArchiveSession command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.commands import ArchiveSessionCommand

class ArchiveSessionHandler(CommandHandler):
    """Archive a completed session."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, command: ArchiveSessionCommand) -> CommandResult:
        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            from datetime import datetime, timezone

            # Mark as archived via context flag
            session = session.model_copy(
                update={
                    "context": session.context.model_copy(update={
                        "archived": True,
                        "archived_at": datetime.now(timezone.utc).isoformat(),
                        "archive_ttl_days": command.ttl_days,
                    })
                }
            )
            await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "ttl_days": command.ttl_days,
                    "status": "archived",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="ARCHIVE_ERROR"
            )
