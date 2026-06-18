"""CompactMemoryHandler — handles CompactMemory command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.commands import CompactMemoryCommand

from weebot.application.services.memory_compactor import MemoryCompactor

class CompactMemoryHandler(CommandHandler):
    """Compact session memory by removing old events."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo
        self._compactor = MemoryCompactor()

    async def handle(self, command: CompactMemoryCommand) -> CommandResult:
        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            before_count = len(session.events)
            session = self._compactor.compact_session(session)
            after_count = len(session.events)

            await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events_before": before_count,
                    "events_after": after_count,
                    "events_removed": before_count - after_count,
                    "status": "compacted",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="COMPACTION_ERROR"
            )

