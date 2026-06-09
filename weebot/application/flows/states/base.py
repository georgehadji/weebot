"""Base class for Flow states."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.domain.models.event import AgentEvent


class AgentStatus(str, Enum):
    """Status of the Plan-Act flow state machine."""
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"   # Per-step code review after execution
    UPDATING = "updating"
    VERIFYING = "verifying"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"


class FlowState(ABC):
    """Abstract base class for all Plan-Act Flow states."""

    # Each subclass overrides this to indicate its position in the
    # state machine.  Used by PlanActFlow.set_state() instead of a
    # hardcoded dict.
    status: AgentStatus = AgentStatus.IDLE

    @abstractmethod
    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        """Execute the state's logic."""
        ...
