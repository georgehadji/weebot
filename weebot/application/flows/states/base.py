"""Base class for Flow states."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, StrEnum
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


# ── State registry (plan 3.6, LAY-2, pattern Q6) ─────────────────────────────
# States used to reach their successors with function-local imports, which tied
# eight modules into one import cycle. A state now names its successor by
# ``StateId`` and asks the registry for it; every state module imports this file
# and nothing imports a sibling. Classes register themselves with
# ``@register_state`` and ``flows/states/__init__.py`` imports them all, so any
# import of a state module populates the registry.


# The result of a failed step that a plan update replaced: COMPLETED, but no work done.
# Here, not in updating.py, because VerifyingState reads it and states never import
# a sibling.
HANDLED_BY_PLAN_UPDATE = "Handled by plan update"


class StateId(StrEnum):
    PLANNING = "planning"
    CRITIQUING = "critiquing"
    PREMORTEM = "premortem"
    PLAN_REVIEW = "plan_review"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    UPDATING = "updating"
    REVIEWING = "reviewing"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"


_STATES: dict[StateId, type[FlowState]] = {}


def register_state(state_id: StateId):
    """Class decorator: make *state_id* resolve to the decorated state class."""

    def decorate(cls: type[FlowState]) -> type[FlowState]:
        _STATES[state_id] = cls
        return cls

    return decorate


def state_class(state_id: StateId) -> type[FlowState]:
    try:
        return _STATES[state_id]
    except KeyError:
        raise LookupError(
            f"no state registered for {state_id!r}; import weebot.application.flows.states"
        ) from None


def new_state(state_id: StateId, *args, **kwargs) -> FlowState:
    """Construct the state registered under *state_id*."""
    return state_class(state_id)(*args, **kwargs)


class ConfidentThresholds:
    """Confidence thresholds for plan critique verdicts."""

    REVISE_THRESHOLD = 0.5
    WARN_THRESHOLD = 0.8


def next_state_after_plan(min_steps: int = 1) -> FlowState:
    """PlanReviewState or ExecutingState, by the plan-review feature flag.

    Call this from any state that transitions to execution after plan creation or
    critique, to insert the plan review gate.
    """
    from weebot.config.settings import get_settings

    if not get_settings().plan_review_enabled:
        return new_state(StateId.EXECUTING)
    return new_state(StateId.PLAN_REVIEW, min_steps=min_steps)
