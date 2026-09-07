"""Base class for Flow states."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING
from collections.abc import AsyncGenerator

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.domain.models.event import AgentEvent


class AgentStatus(str, Enum):
    """Status of the Plan-Act flow state machine."""

    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"  # Per-step code review after execution
    UPDATING = "updating"
    VERIFYING = "verifying"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"


def task_text(context: PlanActFlow, prompt: str) -> str:
    """The task this flow is working on, for a state that wants the *task*.

    `prompt` is the current turn's user input, and after the first state of a
    run it is `""`: `PlanActFlow.run()` hands the turn's text to one state and
    empties it for the rest. That is correct for the two places that want the
    turn input — the executor's `user_input`, which its own comment describes
    as "the user provided input" on a resume, and the behavioural learner's
    correction text — and wrong for every place that wants the task. A plan
    critic scoring a plan against `""` is not scoring it against anything.

    `PlanningState` already carried this fallback inline, with a comment naming
    the run loop's flag. This is that same rule, written once, for the six
    states that need it. (D74.)
    """
    if prompt.strip():
        return prompt
    session_context = getattr(context._session, "context", None)
    if session_context is None:
        return prompt
    return (
        session_context.get("_original_task", "")
        or session_context.get("last_prompt", "")
        or prompt
    )


class FlowState(ABC):
    """Abstract base class for all Plan-Act Flow states."""

    # Each subclass overrides this to indicate its position in the
    # state machine.  Used by PlanActFlow.set_state() instead of a
    # hardcoded dict.
    status: AgentStatus = AgentStatus.IDLE

    @abstractmethod
    async def execute(self, context: PlanActFlow, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        """Execute the state's logic."""
        ...
