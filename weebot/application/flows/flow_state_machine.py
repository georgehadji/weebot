"""FlowStateMachine — pure state-transition logic for PlanActFlow.

Extracted from PlanActFlow.set_state() and the AgentStatus enum.
Each FlowState subclass declares its own status.  This module
simply encodes the transition rules between states.

Usage:
    fsm = FlowStateMachine()
    next_state = fsm.transition(current_state, event_type)
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class AgentStatus(str, Enum):
    """Status of the Plan-Act flow state machine."""
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    UPDATING = "updating"
    VERIFYING = "verifying"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"


# State transition rules: (current_agent_status, event_type) → next_agent_status
# event_type can be "plan_created", "step_completed", "review_approved",
# "review_revised", "review_rejected", "update_completed", "verify_passed",
# "verify_failed"
_TRANSITION_TABLE: dict[tuple[AgentStatus, str], AgentStatus] = {
    (AgentStatus.IDLE, "plan_created"): AgentStatus.PLANNING,
    (AgentStatus.PLANNING, "plan_approved"): AgentStatus.EXECUTING,
    (AgentStatus.EXECUTING, "step_completed"): AgentStatus.REVIEWING,
    (AgentStatus.REVIEWING, "review_approved"): AgentStatus.EXECUTING,
    (AgentStatus.REVIEWING, "review_revised"): AgentStatus.EXECUTING,
    (AgentStatus.REVIEWING, "review_rejected"): AgentStatus.UPDATING,
    (AgentStatus.UPDATING, "update_completed"): AgentStatus.EXECUTING,
    (AgentStatus.EXECUTING, "all_steps_complete"): AgentStatus.VERIFYING,
    (AgentStatus.VERIFYING, "verify_passed"): AgentStatus.SUMMARIZING,
    (AgentStatus.VERIFYING, "verify_failed"): AgentStatus.EXECUTING,
    (AgentStatus.SUMMARIZING, "summary_done"): AgentStatus.COMPLETED,
}


class FlowStateMachine:
    """Pure state machine for PlanActFlow transitions.

    Does NOT hold references to any flow, session, or tool objects.
    """

    @staticmethod
    def transition(current: AgentStatus, event: str) -> Optional[AgentStatus]:
        """Return the next status given the current status and event.

        Args:
            current: The current AgentStatus.
            event: The event type string (e.g. "step_completed").

        Returns:
            The next AgentStatus, or None if no transition is defined.
        """
        return _TRANSITION_TABLE.get((current, event))

    @staticmethod
    def can_transition(current: AgentStatus, event: str) -> bool:
        """Check whether a transition is defined for this (status, event) pair."""
        return (current, event) in _TRANSITION_TABLE

    @staticmethod
    def valid_events_for(status: AgentStatus) -> list[str]:
        """Return all valid event types for a given status."""
        return [
            event for (s, event) in _TRANSITION_TABLE
            if s == status
        ]

    @staticmethod
    def terminal_states() -> set[AgentStatus]:
        """Return statuses that are terminal (no outgoing transitions)."""
        outgoing = {s for (s, _) in _TRANSITION_TABLE}
        return {s for s in AgentStatus if s not in outgoing}
