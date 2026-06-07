"""ChatAgent — simple conversational agent using LLMPort directly.

Unlike PlannerAgent or ExecutorAgent, ChatAgent does not create plans
or execute tool loops.  It sends the conversation history to the LLM
and returns the response as message events.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.config.constants import TEMPERATURE_CREATIVE, DEFAULT_MAX_CHAT_CONTEXT_MESSAGES
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import AgentEvent, MessageEvent

logger = logging.getLogger(__name__)


class ChatAgent:
    """Conversational agent that delegates to LLMPort for chat responses.

    Uses a sliding window of recent messages as conversation context.
    No plan creation, no tool loop, no structured output parsing.
    """

    # Maximum number of recent messages to include as context.
    # Beyond this, older messages are dropped to keep token usage bounded.
    MAX_CONTEXT_MESSAGES = DEFAULT_MAX_CHAT_CONTEXT_MESSAGES

    def __init__(
        self,
        llm: LLMPort,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
    ):
        self._llm = llm
        self._event_bus = event_bus
        self._model = model

    async def respond(
        self,
        message: str,
        history: list[MessageEvent],
    ) -> AsyncGenerator[AgentEvent, None]:
        """Send the user message and conversation history to the LLM.

        Args:
            message: The latest user message.
            history: Previous conversation messages (user + assistant).

        Yields:
            MessageEvent with the LLM response.
        """
        # Build conversation context from history (sliding window)
        context_messages: list[dict[str, str]] = []
        recent = history[-self.MAX_CONTEXT_MESSAGES:] if history else []

        for event in recent:
            if event.type == "message":
                role = getattr(event, "role", "")
                content = getattr(event, "message", "")
                if role and content:
                    context_messages.append({"role": role, "content": content})

        # Add the new user message
        context_messages.append({"role": "user", "content": message})

        try:
            response = await self._llm.chat(
                messages=context_messages,
                model=self._model,
                temperature=TEMPERATURE_CREATIVE,
                max_tokens=4000,
            )

            yield MessageEvent(
                role="assistant",
                message=response.content,
                model=response.model,
                tokens_used=response.usage.get("total_tokens", 0),
                cost=response.usage.get("total_cost", 0.0),
            )

        except Exception as exc:
            logger.error("ChatAgent LLM call failed: %s", exc)
            from weebot.domain.models.event import ErrorEvent

            yield ErrorEvent(error=f"Chat LLM call failed: {exc}")
