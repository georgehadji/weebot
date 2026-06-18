"""SummarizeHandler — handles Summarize command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.commands import SummarizeCommand

# SummarizeHandler delegates to ExecutorAgent — no extra imports needed

class SummarizeHandler(CommandHandler):
    """Generate a final summary via the executor agent through the mediator."""

    def __init__(self, llm: LLMPort, state_repo: StateRepositoryPort | None = None):
        self._llm = llm
        self._state_repo = state_repo

    async def handle(self, command: SummarizeCommand) -> CommandResult:
        from weebot.application.agents.executor import ExecutorAgent

        try:
            # Load session if state_repo is available (best-effort —
            # the flow state also persists via _emit, but direct
            # callers of this handler need their own persistence).
            if self._state_repo:
                session = await self._state_repo.load_session(command.session_id)
            else:
                session = None

            executor = ExecutorAgent(llm=self._llm)
            events: list[dict] = []
            async for event in executor.summarize():
                events.append(event.model_dump())
                if session is not None:
                    session = session.add_event(event)

            if session is not None:
                await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events": events,
                    "status": "summarized",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="SUMMARIZE_ERROR"
            )

