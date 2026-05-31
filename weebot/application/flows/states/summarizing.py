"""Summarizing state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import FlowState
from weebot.domain.models.event import AgentEvent

logger = logging.getLogger(__name__)

class SummarizingState(FlowState):
    """Handles the generation of the final task summary."""

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.completed import CompletedState

        async for event in context._executor.summarize():
            await context._emit(event)
            yield event

        context.set_state(CompletedState())
