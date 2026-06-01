"""ChatFlow — conversational chat state machine.

Shares the BaseFlow/FlowState infrastructure with PlanActFlow but
uses a simpler 2-state loop (ChatMessage → Idle → ChatMessage …).

CQRS delegate pattern: ProcessMessageHandler owns the ChatAgent call.
The flow state consumes serialised events from CommandResult.data["events"].
When no mediator is configured, falls back to direct agent call.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Optional, TYPE_CHECKING

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import AgentEvent, MessageEvent
from weebot.domain.models.session import Session, SessionStatus

if TYPE_CHECKING:
    from weebot.application.cqrs.mediator import Mediator
    from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)


class ChatFlow(BaseFlow):
    """Conversational agent flow with ChatMessage → Idle state machine."""

    MAX_EXCHANGES = 500  # Max message exchanges before auto-ending

    def __init__(
        self,
        llm: LLMPort,
        session: Session,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        mediator: Optional[Mediator] = None,
        state_repo: Optional[StateRepositoryPort] = None,
    ):
        self._llm = llm
        self._session = session
        self._event_bus = event_bus
        self._model = model
        self._mediator = mediator
        self._state_repo = state_repo
        self._exchange_count = 0
        self._done = False
        self._current_state = None
        self._next_state = None
        self._emit_lock = asyncio.Lock()

    def is_done(self) -> bool:
        return self._done

    def set_state(self, state) -> None:
        self._next_state = state

    async def _emit(self, event: AgentEvent) -> None:
        """Persist and publish an event."""
        async with self._emit_lock:
            self._session = self._session.add_event(event)
            if self._state_repo:
                await self._state_repo.save_session(self._session)
            if self._event_bus:
                await self._event_bus.publish(event)

    async def run(self, prompt: str = "") -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.chat_message import ChatMessageState
        from weebot.application.flows.states.idle import IdleState

        self._session = self._session.set_status(SessionStatus.RUNNING)
        self._current_state = ChatMessageState()
        self._next_state = None

        while not self._done and self._exchange_count < self.MAX_EXCHANGES:
            # If an external state transition was requested (e.g., from CLI resume)
            if self._next_state is not None:
                self._current_state = self._next_state
                self._next_state = None

            async for event in self._current_state.execute(self, prompt):
                await self._emit(event)
                yield event

                # Detect final states
                from weebot.domain.models.event import DoneEvent
                if isinstance(event, DoneEvent):
                    self._done = True
                    break

                # On WaitForUserEvent, transition to idle
                from weebot.domain.models.event import WaitForUserEvent
                if isinstance(event, WaitForUserEvent):
                    self.set_state(IdleState())
                    break

            # If still running and no explicit transition, cycle back to message state
            if not self._done and self._next_state is None:
                self.set_state(ChatMessageState())

            self._exchange_count += 1
            # After the first message, prompt is user input from the session context
            prompt = ""

        if not self._done:
            logger.info("ChatFlow max exchanges (%d) reached — ending session", self.MAX_EXCHANGES)
            self._session = self._session.set_status(SessionStatus.COMPLETED)
            if self._state_repo:
                await self._state_repo.save_session(self._session)

        from weebot.domain.models.event import DoneEvent
        yield DoneEvent()
        self._done = True
