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
    UNVERIFIED = "unverified"  # executed, but evidence did not support completion


class PlanStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    RUNNING = "running"
    COMPLETED = "completed"


class ContextScope(str, Enum):
    """What context sources a step needs in its executor prompt.

    Set by the planner at plan-creation time. The prompt builder uses this
    to select which sources to assemble, following the ICM principle of
    stage-scoped context loading — a step that runs a shell command doesn't
    need the same context as one drafting user-facing copy.
    """
    FULL = "full"          # all sources (default — backward compatible)
    MINIMAL = "minimal"    # base prompt + harness only (shell/file/mechanical steps)
    SKILL = "skill"        # + matched skills (technical/code steps)
    CREATIVE = "creative"  # + user profile + personality (user-facing content)


class Step(BaseModel):
    """A single step in a plan."""
    id: str = Field(default="", description="Step identifier")
    description: str = Field(default="", description="What this step does")
    status: StepStatus = Field(default=StepStatus.PENDING)
    result: Optional[str] = Field(default=None, description="Summary of execution result")
    retry_count: int = 0  # Phase 3: tracks retries for step validation (cap at 1)
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="Planner-authored conditions the executed step must satisfy "
                    "before it can be marked COMPLETED (LH-Harness subtask contract cᵢ).",
    )
    evidence_refs: List[str] = Field(
        default_factory=list,
        description="References (file paths, tool-event ids) to the evidence "
                    "that supported this step's status.",
    )
    context_scope: ContextScope = Field(
        default=ContextScope.FULL,
        description="Which context sources the executor prompt builder loads "
                    "for this step. Planner-assigned; FULL preserves prior behavior.",
    )

    def is_done(self) -> bool:
        return self.status in (StepStatus.COMPLETED, StepStatus.FAILED)

    def mark_running(self) -> "Step":
        return self.model_copy(update={"status": StepStatus.RUNNING})

    def mark_completed(self, result: Optional[str] = None, evidence_refs: Optional[List[str]] = None) -> "Step":
        updates: dict = {"status": StepStatus.COMPLETED}
        if result is not None:
            updates["result"] = result
        if evidence_refs is not None:
            updates["evidence_refs"] = evidence_refs
        return self.model_copy(update=updates)

    def mark_failed(self, result: Optional[str] = None) -> "Step":
        updates: dict = {"status": StepStatus.FAILED}
        if result is not None:
            updates["result"] = result
        return self.model_copy(update=updates)

    def mark_unverified(self, reason: str, evidence_refs: Optional[List[str]] = None) -> "Step":
        """Step executed, but evidence did not support completion.

        Distinct from FAILED: the executor did not error, but the
        environment-grounded check found no supporting evidence
        (or contradicting evidence). Not done — eligible for retry,
        bounded by retry_count.
        """
        updates: dict = {"status": StepStatus.UNVERIFIED, "result": reason}
        if evidence_refs is not None:
            updates["evidence_refs"] = evidence_refs
        return self.model_copy(update=updates)

    def is_blocked(self, predecessor_sibling: Optional["Step"] = None) -> bool:
        """Return True if this step is blocked by an incomplete predecessor.

        Args:
            predecessor_sibling: The step that must complete before this
                one runs.  ``None`` means no dependency (first step).
        """
        if predecessor_sibling is None:
            return False
        return not predecessor_sibling.is_done()


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
    # Enhancement 4: tracks how many times the planner's step-splitting heuristics
    # fired during plan parsing (proxy for decomposition granularity problems).
    _heuristic_splits: int = 0

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

        Keeps completed (and unverified — awaiting retry, not yet resolved)
        steps from the original and appends new pending steps from the
        updated plan. Deduplicates by both step ID and description prefix
        (first 80 chars) to prevent the LLM from re-adding already-done or
        already-attempted work under fresh IDs.
        """
        retained = [
            s for s in self.steps
            if s.is_done() or s.status is StepStatus.UNVERIFIED
        ]
        retained_ids = {s.id for s in retained}
        retained_descs = {s.description.strip().lower()[:80] for s in retained}
        fresh = [
            s for s in updated.steps
            if not s.is_done()
            and s.status is not StepStatus.UNVERIFIED
            and s.id not in retained_ids
            and s.description.strip().lower()[:80] not in retained_descs
        ]
        return self.model_copy(update={"steps": retained + fresh, "status": PlanStatus.UPDATED})

    def is_complete(self) -> bool:
        return len(self.steps) > 0 and all(s.is_done() for s in self.steps)

    # ── Domain validation methods (migrated from application layer) ──

    def is_valid(self) -> tuple[bool, list[str]]:
        """Validate plan consistency and completeness.

        Returns:
            (is_valid, errors) where errors is a list of human-readable
            validation messages.  An empty errors list means valid.
        """
        errors: list[str] = []
        if not self.title.strip():
            errors.append("Plan must have a non-empty title")
        if not self.steps:
            errors.append("Plan must have at least one step")
        for i, step in enumerate(self.steps):
            if not step.description.strip():
                errors.append(f"Step {i+1} has no description")
        return (len(errors) == 0, errors)

    def remaining_budget(self, max_iterations: int) -> int:
        """Return how many iterations remain before hitting *max_iterations*."""
        consumed = len(self.get_completed_steps())
        return max(0, max_iterations - consumed)

    def validate_step_descriptions(self) -> list[str]:
        """Return warnings for anomalous step descriptions.
        Checks for empty descriptions and near-duplicates (first 80 chars)."""
        warnings: list[str] = []
        seen_prefixes: set[str] = set()
        for i, step in enumerate(self.steps):
            if not step.description.strip():
                warnings.append(f"Step {i+1} has empty description")
                continue
            prefix = step.description.strip().lower()[:80]
            if prefix in seen_prefixes:
                warnings.append(f"Step {i+1} is near-duplicate of a previous step")
            seen_prefixes.add(prefix)
        return warnings
