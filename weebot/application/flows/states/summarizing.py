"""Summarizing state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent

logger = logging.getLogger(__name__)

class SummarizingState(FlowState):
    """Handles the generation of the final task summary."""
    status = AgentStatus.SUMMARIZING

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.completed import CompletedState

        # Prefer CQRS mediator path; fallback to direct agent call
        if context._mediator:
            from weebot.application.cqrs.commands import SummarizeCommand
            from weebot.application.cqrs.event_reconstructor import reconstruct_events

            result = await context._mediator.send(
                SummarizeCommand(session_id=context._session.id)
            )
            if result.success:
                for event in reconstruct_events(result.data.get("events", [])):
                    await context._emit(event)
                    yield event
            else:
                logger.warning("SummarizeCommand failed: %s", result.error)
        else:
            import warnings
            warnings.warn(
                "SummarizingState: no mediator available, using direct agent call",
                DeprecationWarning, stacklevel=2,
            )
            async for event in context._executor.summarize():
                await context._emit(event)
                yield event

        context.set_state(CompletedState())
