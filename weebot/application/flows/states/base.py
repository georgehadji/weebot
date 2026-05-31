"""Base class for Flow states."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.domain.models.event import AgentEvent


class FlowState(ABC):
    """Abstract base class for all Plan-Act Flow states."""

    @abstractmethod
    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        """Execute the state's logic."""
        ...
