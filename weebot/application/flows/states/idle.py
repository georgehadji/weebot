"""IdleState — wait for the next user input.

Transition: user sends a message → ChatMessageState.
Timeouts and disconnect are handled by the session lifecycle.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

from weebot.application.flows.states.base import FlowState
from weebot.domain.models.event import AgentEvent, WaitForUserEvent
from weebot.domain.models.session import SessionStatus

if TYPE_CHECKING:
    from weebot.application.flows.chat_flow import ChatFlow

logger = logging.getLogger(__name__)


class IdleState(FlowState):
    """Wait for next user input.

    This state yields a WaitForUserEvent and pauses the flow.
    External code (CLI or web route) resumes the flow with the next
    user message by calling flow.run() again with the new prompt.
    """

    async def execute(
        self, context: ChatFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        # If user already provided the next message, skip waiting
        if prompt:
            from weebot.application.flows.states.chat_message import ChatMessageState
            context.set_state(ChatMessageState())
            return

        # Mark session as waiting for input
        context._session = context._session.set_status(SessionStatus.WAITING)
        yield WaitForUserEvent(
            question="Waiting for user input",
        )
