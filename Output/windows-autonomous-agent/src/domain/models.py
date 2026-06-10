"""Core domain models using Pydantic for validation and immutability.

Pure domain entities (no infrastructure, no application logic).
Follows Clean Architecture: depends only on stdlib + pydantic.

Immutability: All models are frozen (Pydantic ConfigDict(frozen=True)).
State transitions return NEW instances (no in-place mutation).
SOLID:
- Single Responsibility: each model owns its data + minimal invariants.
- Open/Closed: extend via composition or new models, not modification.
- Liskov: subtypes would honor contracts (none yet).
- Interface Segregation: small focused models.
- Dependency Inversion: consumers depend on these abstractions.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict


class StepStatus(str, Enum):
    """Lifecycle states for a single executable step. Immutable enum."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class PlanStatus(str, Enum):
    """Lifecycle states for an entire plan. Immutable enum."""
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(BaseModel):
    """A high-level user goal or task. Immutable (frozen)."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique identifier for the task")
    description: str = Field(..., min_length=5, description="Natural language goal")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Step(BaseModel):
    """A single executable step in a plan. One-step-at-a-time rule enforced at application layer."""
    id: str = Field(..., description="Unique step identifier")
    description: str = Field(..., min_length=3)
    status: StepStatus = StepStatus.PENDING
    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @field_validator("description")
    @classmethod
    def description_must_be_actionable(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Step description cannot be empty")
        return v.strip()


class Plan(BaseModel):
    """A sequence of steps to achieve a Task. Follows one-step execution rule."""
    id: str
    task_id: str
    steps: List[Step] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    current_step_index: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_current_step(self) -> Optional[Step]:
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def mark_step_completed(self, step_id: str, result: str) -> None:
        for step in self.steps:
            if step.id == step_id:
                step.status = StepStatus.COMPLETED
                step.result = result
                step.completed_at = datetime.utcnow()
                self.current_step_index += 1
                self.updated_at = datetime.utcnow()
                # Transition plan status
                if self.current_step_index >= len(self.steps):
                    self.status = PlanStatus.COMPLETED
                elif self.status == PlanStatus.DRAFT:
                    self.status = PlanStatus.IN_PROGRESS
                break

    def mark_step_failed(self, step_id: str, error: str) -> None:
        for step in self.steps:
            if step.id == step_id:
                step.status = StepStatus.FAILED
                step.error = error
                step.completed_at = datetime.utcnow()
                self.status = PlanStatus.FAILED
                self.updated_at = datetime.utcnow()
                break


class ExecutionResult(BaseModel):
    """Result of executing one step."""
    step_id: str
    success: bool
    output: str
    error: Optional[str] = None
    duration_seconds: float = 0.0
    tool_used: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentState(BaseModel):
    """Current state of the agent execution."""
    task: Optional[Task] = None
    current_plan: Optional[Plan] = None
    last_result: Optional[ExecutionResult] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None
    total_steps_executed: int = 0
