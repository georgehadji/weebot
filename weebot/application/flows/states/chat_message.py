"""ChatMessageState — process a single user message through the LLM.

Uses the CQRS delegate pattern: dispatches ProcessMessageCommand through
the mediator, consumes serialised events from CommandResult.data["events"].
Falls back to direct ChatAgent call when no mediator is configured.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

from weebot.application.flows.states.base import FlowState
from weebot.domain.models.event import AgentEvent, ErrorEvent, MessageEvent

if TYPE_CHECKING:
    from weebot.application.flows.chat_flow import ChatFlow

logger = logging.getLogger(__name__)


class ChatMessageState(FlowState):
    """Process a single conversational turn.

    Every user message enters this state, which passes it through the
    mediator (or ChatAgent directly) and yields the response as events.
    """

    async def execute(
        self, context: ChatFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        if not prompt:
            return

        # ── Inject pending commitment summary ──────────────────
        if context._state_repo and hasattr(context._state_repo, 'get_pending_commitments'):
            try:
                from weebot.domain.services.commitment_engine import CommitmentEngine
                engine = CommitmentEngine(state_repo=context._state_repo)
                summary = await engine.get_pending_summary()
                if summary:
                    prompt = summary + "\n\n───\n\n" + prompt
            except Exception:
                logger.debug("Failed to load pending summary from CommitmentEngine", exc_info=True)

        # --- CQRS delegate path ---
        if context._mediator:
            from weebot.application.cqrs.commands import ProcessMessageCommand

            history_events = [
                e for e in context._session.events
                if e.type == "message" and getattr(e, "role", "") in ("user", "assistant")
            ]

            cmd_result = await context._mediator.send(
                ProcessMessageCommand(
                    session_id=context._session.id,
                    message=prompt,
                    model=context._model or "",
                    history=[h.model_dump() for h in history_events[-50:]],
                    exchange_count=context._exchange_count,
                )
            )
            if not cmd_result.success:
                yield ErrorEvent(error=f"Chat processing rejected: {cmd_result.error}")
                return

            # Consume events from the mediator result.
            # Consume events via shared reconstructor.
            from weebot.application.cqrs.event_reconstructor import reconstruct_events
            for event in reconstruct_events(cmd_result.data.get("events", [])):
                yield event

        else:
            # Fallback: direct agent call
            from weebot.application.agents.chat_agent import ChatAgent

            agent = ChatAgent(
                llm=context._llm,
                event_bus=context._event_bus,
                model=context._model,
            )
            # Build history from session events
            history = [
                e for e in context._session.events
                if e.type == "message" and getattr(e, "role", "") in ("user", "assistant")
            ]
            async for event in agent.respond(prompt, history):
                yield event

        # Persist the updated session now that all events have been yielded.
        if context._state_repo:
            try:
                await context._state_repo.save_session(context._session)
            except Exception as exc:
                logger.debug("save_session failed in ChatMessageState (non-fatal): %s", exc)
