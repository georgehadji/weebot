"""ProcessMessageHandler — handles ProcessMessage command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.commands import ProcessMessageCommand

class ProcessMessageHandler(CommandHandler):
    """Process a chat message through ChatAgent and return events.

    This handler owns the ChatAgent call so pipeline behaviours
    (LoggingBehavior, ValidationBehavior) activate on every message.
    """

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
    ):
        self._state_repo = state_repo
        self._llm = llm

    async def handle(self, command: ProcessMessageCommand) -> CommandResult:
        from weebot.application.agents.chat_agent import ChatAgent

        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            agent = ChatAgent(
                llm=self._llm,
                model=command.model or None,
            )
            # Reconstruct MessageEvent list from history dicts
            history = []
            for h in command.history:
                from weebot.domain.models.event import MessageEvent
                history.append(MessageEvent(
                    role=h.get("role", "user"),
                    message=h.get("message", h.get("content", "")),
                ))

            events: list[dict] = []
            async for event in agent.respond(command.message, history):
                events.append(event.model_dump())

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events": events,
                    "exchange_count": command.exchange_count + 1,
                    "status": "message_processed",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="CHAT_ERROR"
            )

