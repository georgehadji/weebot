"""Structured event model for agent observability."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
import uuid

from pydantic import BaseModel, Field

from .plan import PlanStatus, StepStatus


class ToolStatus(str, Enum):
    CALLING = "calling"
    CALLED = "called"


class BaseEvent(BaseModel):
    type: Literal[""] = ""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ErrorEvent(BaseEvent):
    type: Literal["error"] = "error"
    error: str = Field(default="")


class PlanEvent(BaseEvent):
    type: Literal["plan"] = "plan"
    status: PlanStatus = Field(default=PlanStatus.CREATED)
    plan: Optional[Any] = Field(default=None)
    step: Optional[Any] = Field(default=None)


class StepEvent(BaseEvent):
    type: Literal["step"] = "step"
    step_id: str = Field(default="")
    description: str = Field(default="")
    status: StepStatus = Field(default=StepStatus.STARTED)


class ToolEvent(BaseEvent):
    type: Literal["tool"] = "tool"
    tool_call_id: str = Field(default="")
    tool_name: str = Field(default="")
    function_name: str = Field(default="")
    function_args: Dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus = Field(default=ToolStatus.CALLING)
    result: Optional[str] = Field(default=None)
    artifact: Optional[Any] = Field(default=None)


class MessageEvent(BaseEvent):
    type: Literal["message"] = "message"
    role: Literal["user", "assistant"] = Field(default="assistant")
    message: str = Field(default="")


class TitleEvent(BaseEvent):
    type: Literal["title"] = "title"
    title: str = Field(default="")


class DoneEvent(BaseEvent):
    type: Literal["done"] = "done"


class WaitForUserEvent(BaseEvent):
    type: Literal["wait_for_user"] = "wait_for_user"
    question: str = Field(default="")


class NotificationEvent(BaseEvent):
    type: Literal["notification"] = "notification"
    text: str = Field(default="")


class ThoughtEvent(BaseEvent):
    """Emitted when the agent explains its reasoning before acting."""
    type: Literal["thought"] = "thought"
    step_id: str = Field(default="")
    thought: str = Field(default="")
    iteration: int = Field(default=0)
    code_review_result: Optional[dict] = Field(
        default=None,
        description="Structured CodeReviewResult dict, set by ReviewingState when verdict is present",
    )


class SteeringEvent(BaseEvent):
    """User-injected mid-execution feedback (Phase 5 — Steering).

    Unlike WaitForUserEvent (which pauses the flow), SteeringEvent is
    non-blocking — the flow continues but adapts its next step based
    on the message.  Sent via SteeringPort from CLI stdin or WebSocket.
    """
    type: Literal["steering"] = "steering"
    session_id: str = Field(default="")
    message: str = Field(default="")


class CanonicalizationEvent(BaseEvent):
    """Emitted when the Action Canonicalizer validates a tool call (Tier 1.1).

    Records what was corrected or blocked for audit and harness evolution.
    """
    type: Literal["canonicalization"] = "canonicalization"
    tool_name: str = Field(default="")
    verdict: str = Field(default="")
    changes: list[str] = Field(default_factory=list)
    block_reason: str = Field(default="")


class TodoEvent(BaseEvent):
    """Self-reported progress checklist item (Enhancement 4)."""
    type: Literal["todo"] = "todo"
    session_id: str = Field(default="")
    step_id: str = Field(default="")
    action: str = Field(default="")         # "add" | "update" | "complete"
    description: str = Field(default="")
    status: str = Field(default="pending")  # "pending" | "in_progress" | "completed" | "failed"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)


class VerificationEvent(BaseEvent):
    """Emitted during Chain-of-Verification (CoVe) fact-checking.

    Each event represents one verification question + answer pair.
    ``consistent`` is True when the answer matches the original claim,
    False when it contradicts.
    """
    type: Literal["verification"] = "verification"
    step_id: str = Field(default="")
    question: str = Field(default="")
    answer: str = Field(default="")
    consistent: bool = Field(default=True)


class TrajectoryDiagnosisEvent(BaseEvent):
    """Emitted when TrajectoryMonitor detects a degenerate pattern (Tier 1.3)."""
    type: Literal["trajectory_diagnosis"] = "trajectory_diagnosis"
    step_id: str = Field(default="")
    health: str = Field(default="")
    detail: str = Field(default="")
    recovery_message: str | None = Field(default=None)


AgentEvent = Union[
    ErrorEvent,
    PlanEvent,
    StepEvent,
    ToolEvent,
    MessageEvent,
    TitleEvent,
    DoneEvent,
    WaitForUserEvent,
    NotificationEvent,
    ThoughtEvent,
    SteeringEvent,
    CanonicalizationEvent,
    TrajectoryDiagnosisEvent,
    VerificationEvent,
    TodoEvent,
]


class DomainEvent(BaseModel):
    """Base class for all internal domain events."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str = ""


class FactDiscovered(DomainEvent):
    """Event emitted when a new fact is learned."""
    type: str = "fact_discovered"
    session_id: str
    key: str
    value: Any


class MemoryCompacted(DomainEvent):
    """Event emitted when session memory is compacted."""
    type: str = "memory_compacted"
    session_id: str
    events_removed: int


class PlanStepCompleted(DomainEvent):
    """Event emitted when a plan step reaches completion."""
    type: str = "plan_step_completed"
    session_id: str
    step_id: str


# ---------------------------------------------------------------------------
# SkillOpt — trajectory evidence and skill-edit events
# ---------------------------------------------------------------------------


class TrajectoryScored(DomainEvent):
    """Emitted when a task execution completes with a benchmark score."""
    type: str = "trajectory_scored"
    session_id: str
    task_id: str
    score: float
    failure_modes: list[str]
    success_patterns: list[str]
    trajectory_summary: str
    harness: str = "direct_chat"


class SkillEditProposed(DomainEvent):
    """Emitted when the optimizer proposes an edit to a skill."""
    type: str = "skill_edit_proposed"
    skill_name: str
    skill_version: int
    edit: Any = None
    support_count: int = 1
    source_type: str = "failure"


class SkillEditAccepted(DomainEvent):
    """Emitted when a proposed edit passes the validation gate."""
    type: str = "skill_edit_accepted"
    skill_name: str
    old_version: int
    new_version: int
    validation_score_delta: float
    edit: Any = None


class SkillEditRejected(DomainEvent):
    """Emitted when a proposed edit fails the validation gate."""
    type: str = "skill_edit_rejected"
    skill_name: str
    skill_version: int
    score_drop: float
    edit: Any = None
    failure_analysis: str = ""


class EpochCompleted(DomainEvent):
    """Emitted at the end of an optimization epoch."""
    type: str = "epoch_completed"
    skill_name: str
    epoch: int
    best_validation_score: float
    edits_accepted: int
    edits_rejected: int
    slow_update_applied: bool = False
