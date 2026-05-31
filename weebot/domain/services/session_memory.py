"""Indexed session memory for O(1) event-type lookups."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Optional

from weebot.domain.models.event import AgentEvent, MessageEvent, PlanEvent, WaitForUserEvent
from weebot.domain.models.plan import Plan


class SessionMemory:
    """Maintains a type-index over session events to avoid O(n) scans."""

    def __init__(self, max_recent_per_type: int = 100) -> None:
        self._index: defaultdict[str, deque[int]] = defaultdict(
            lambda: deque(maxlen=max_recent_per_type)
        )

    def index_event(self, idx: int, event: AgentEvent) -> None:
        """Register an event at the given list index."""
        self._index[event.type].append(idx)

    def find_last_plan(self, events: list[AgentEvent]) -> Optional[Plan]:
        """Return the most recent PlanEvent.plan with step statuses reconciled.

        Step statuses are stored in StepEvents, NOT in the PlanEvent itself.
        This method finds the last PlanEvent and then applies status changes
        from any StepEvents that occurred after it, so resumed sessions don't
        re-execute already-completed steps.
        """
        from weebot.domain.models.event import StepEvent

        plan_indices = self._index.get("plan", [])
        if not plan_indices:
            return None

        last_plan_idx = max(plan_indices)
        event = events[last_plan_idx]
        if not isinstance(event, PlanEvent) or event.plan is None:
            return None

        plan = (
            Plan.model_validate(event.plan)
            if isinstance(event.plan, dict)
            else event.plan
        )

        # Reconcile step statuses from StepEvents that happened AFTER this plan
        step_indices = self._index.get("step", [])
        for step_idx in step_indices:
            if step_idx <= last_plan_idx:
                continue
            step_event = events[step_idx]
            if isinstance(step_event, StepEvent) and step_event.step_id:
                # Map StepEvent status to StepStatus
                from weebot.domain.models.plan import StepStatus as PS
                status_map = {
                    "started": PS.RUNNING,
                    "running": PS.RUNNING,
                    "completed": PS.COMPLETED,
                    "failed": PS.FAILED,
                }
                new_status = status_map.get(step_event.status, None)
                if new_status is not None:
                    plan = plan.update_step_status(step_event.step_id, new_status)

        return plan

    def has_unresolved_wait_event(self, events: list[AgentEvent]) -> bool:
        """Check if the last WaitForUserEvent has no subsequent user MessageEvent."""
        for idx in reversed(self._index.get("wait_for_user", [])):
            event = events[idx]
            if isinstance(event, WaitForUserEvent):
                for later_idx in range(idx + 1, len(events)):
                    later = events[later_idx]
                    if isinstance(later, MessageEvent) and later.role == "user":
                        return False
                return True
        return False
