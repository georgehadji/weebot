"""Session domain model — tracks a conversation/task lifecycle."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, PrivateAttr

from .plan import Plan
from .event import AgentEvent
from weebot.domain.services.session_memory import SessionMemory


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class Session(BaseModel):
    """A user session containing events, plan history, and metadata."""
    id: str = Field(default="")
    user_id: str = Field(default="")
    agent_id: str = Field(default="")
    status: SessionStatus = Field(default=SessionStatus.PENDING)
    title: Optional[str] = Field(default=None)
    events: List[AgentEvent] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    _memory_index: SessionMemory = PrivateAttr(default_factory=SessionMemory)

    def add_event(self, event: AgentEvent) -> "Session":
        events = list(self.events)
        events.append(event)
        new_session = self.model_copy(update={
            "events": events,
            "updated_at": datetime.now(timezone.utc),
        })
        new_session._memory_index.index_event(len(events) - 1, event)
        return new_session

    def set_status(self, status: SessionStatus) -> "Session":
        return self.model_copy(update={
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        })

    def get_last_plan(self) -> Optional[Plan]:
        plan = self._memory_index.find_last_plan(self.events)
        if plan is not None:
            return plan
        # Fallback scan for safety / backwards compatibility.
        # Also reconciles step statuses from StepEvents that occurred
        # after the last PlanEvent.
        from .event import PlanEvent, StepEvent
        from .plan import Plan, StepStatus as PS
        last_plan = None
        last_plan_idx = -1
        for i, event in enumerate(self.events):
            if isinstance(event, PlanEvent) and event.plan is not None:
                if isinstance(event.plan, dict):
                    last_plan = Plan.model_validate(event.plan)
                else:
                    last_plan = event.plan
                last_plan_idx = i
        if last_plan is None:
            return None

        # Apply step statuses from StepEvents after the last plan
        for event in self.events[last_plan_idx + 1:]:
            if isinstance(event, StepEvent) and event.step_id:
                status_map = {
                    "started": PS.RUNNING,
                    "running": PS.RUNNING,
                    "completed": PS.COMPLETED,
                    "failed": PS.FAILED,
                }
                new_status = status_map.get(event.status, None)
                if new_status is not None:
                    last_plan = last_plan.update_step_status(event.step_id, new_status)

        return last_plan

    def has_unresolved_wait_event(self) -> bool:
        return self._memory_index.has_unresolved_wait_event(self.events)

    def set_title(self, title: str) -> "Session":
        return self.model_copy(update={"title": title})

    def add_user_message(self, text: str) -> "Session":
        from .event import MessageEvent
        return self.add_event(MessageEvent(role="user", message=text))

    def set_fact(self, key: str, value: Any) -> "Session":
        facts = dict(self.context.get("facts", {}))
        facts[key] = value
        new_context = dict(self.context)
        new_context["facts"] = facts
        return self.model_copy(update={"context": new_context})

    def get_fact(self, key: str, default: Any = None) -> Any:
        return self.context.get("facts", {}).get(key, default)

    def get_facts(self) -> dict[str, Any]:
        return dict(self.context.get("facts", {}))
