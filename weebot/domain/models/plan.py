"""Plan domain model — immutable task breakdown with rich behavior."""
from __future__ import annotations

from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    RUNNING = "running"
    COMPLETED = "completed"


class Step(BaseModel):
    """A single step in a plan."""
    id: str = Field(default="", description="Step identifier")
    description: str = Field(default="", description="What this step does")
    status: StepStatus = Field(default=StepStatus.PENDING)
    result: Optional[str] = Field(default=None, description="Summary of execution result")
    retry_count: int = 0  # Phase 3: tracks retries for step validation (cap at 1)

    def is_done(self) -> bool:
        return self.status in (StepStatus.COMPLETED, StepStatus.FAILED)

    def mark_running(self) -> "Step":
        return self.model_copy(update={"status": StepStatus.RUNNING})

    def mark_completed(self, result: Optional[str] = None) -> "Step":
        updates: dict = {"status": StepStatus.COMPLETED}
        if result is not None:
            updates["result"] = result
        return self.model_copy(update=updates)

    def mark_failed(self, result: Optional[str] = None) -> "Step":
        updates: dict = {"status": StepStatus.FAILED}
        if result is not None:
            updates["result"] = result
        return self.model_copy(update=updates)


class PlanCritique(BaseModel):
    """LLM-generated critique of a plan before execution.

    Evaluates step-by-step viability, tool choice, and scope before
    the plan reaches the executor.
    """
    plan_id: str = Field(default="", description="The plan being critiqued")
    step_scores: dict[str, float] = Field(
        default_factory=dict,
        description="step_id -> 0.0-1.0 confidence score",
    )
    flaws: list[str] = Field(
        default_factory=list,
        description="Specific concerns about the plan",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Concrete fixes for identified flaws",
    )
    overall_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Overall confidence that the plan will succeed",
    )
    verdict: str = Field(
        default="approved",
        description="'approved' | 'revise' | 'reject'",
    )


class Plan(BaseModel):
    """A structured plan with steps."""
    title: str = Field(default="", description="Plan title")
    message: str = Field(default="", description="Initial message/plan summary")
    steps: List[Step] = Field(default_factory=list)
    status: PlanStatus = Field(default=PlanStatus.CREATED)

    def get_next_step(self) -> Optional[Step]:
        """Return the first step that is not done."""
        for step in self.steps:
            if not step.is_done():
                return step
        return None

    def get_pending_steps(self) -> List[Step]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def get_completed_steps(self) -> List[Step]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]

    def replace_step(self, step_id: str, new_step: Step) -> "Plan":
        """Replace a step by id, returning a new Plan."""
        new_steps = [new_step if s.id == step_id else s for s in self.steps]
        return self.model_copy(update={"steps": new_steps})

    def update_step_status(self, step_id: str, status: StepStatus, result: Optional[str] = None) -> "Plan":
        """Update a step's status by id, returning a new Plan."""
        new_steps: List[Step] = []
        for s in self.steps:
            if s.id == step_id:
                kwargs: dict = {"status": status}
                if result is not None:
                    kwargs["result"] = result
                new_steps.append(s.model_copy(update=kwargs))
            else:
                new_steps.append(s)
        return self.model_copy(update={"steps": new_steps})

    def merge(self, updated: "Plan") -> "Plan":
        """Merge an updated plan with this one.

        Keeps completed steps from the original and appends new pending steps
        from the updated plan. Filters out any steps from updated that have
        the same ID as already-completed steps (prevents duplicates).
        """
        completed = [s for s in self.steps if s.is_done()]
        completed_ids = {s.id for s in completed}
        # Only add fresh steps that aren't already completed
        fresh = [s for s in updated.steps if not s.is_done() and s.id not in completed_ids]
        return self.model_copy(update={"steps": completed + fresh, "status": PlanStatus.UPDATED})

    def is_complete(self) -> bool:
        return len(self.steps) > 0 and all(s.is_done() for s in self.steps)
