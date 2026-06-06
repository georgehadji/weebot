"""FlowCheckpoint — domain model for mid-flow state serialization.

Enables PlanActFlow (and future flows) to save and resume execution from
any state, making long-running agent tasks resilient to process restarts.

A checkpoint captures: the current flow state, the plan with per-step
statuses, completed step results, and a compacted conversation summary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from weebot.domain.models.plan import Plan


class StepCheckpoint(BaseModel):
    """Snapshot of a single step's execution result within a checkpoint."""
    step_id: str = Field(min_length=1)
    description: str = ""
    status: str = Field(default="pending")  # pending | running | completed | failed
    result: Optional[str] = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class FlowCheckpoint(BaseModel):
    """Serializable snapshot of a flow's entire execution state.

    All fields are JSON-serializable via ``model_dump()`` / ``model_validate()``.
    Round-trip fidelity is verified by unit tests.
    """

    session_id: str = Field(min_length=1)
    flow_type: str = Field(
        default="PlanActFlow",
        description="Fully-qualified flow class name for reconstruction.",
    )
    current_state: str = Field(
        default="planning",
        description="Name of the current flow state (planning|executing|updating|summarizing|completed).",
    )
    plan_snapshot: Plan = Field(
        description="Frozen copy of the plan with current step statuses.",
    )
    completed_steps: list[StepCheckpoint] = Field(
        default_factory=list,
        description="Steps that have already completed, with their results.",
    )
    conversation_summary: str = Field(
        default="",
        description="Compacted context from MemoryCompactor so the flow can resume.",
    )
    iteration_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary flow-specific metadata (e.g. sub-agent IDs, tool state).",
    )

    @property
    def pending_step_ids(self) -> list[str]:
        """Return IDs of steps that still need execution."""
        completed_ids = {s.step_id for s in self.completed_steps}
        return [s.id for s in self.plan_snapshot.steps if s.id not in completed_ids]

    @property
    def is_fully_complete(self) -> bool:
        """True when all plan steps have been completed or failed."""
        return len(self.pending_step_ids) == 0
