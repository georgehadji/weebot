"""Iteration context — mutable state snapshot for a single PlanActFlow iteration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from weebot.domain.models.plan import Plan
from weebot.domain.models.session import Session


@dataclass
class IterationContext:
    """Immutable snapshot of flow state for one iteration.

    Created at the start of each ``run()`` loop iteration so that
    all sub-components observe a consistent view of the world.
    """

    session: Session
    plan: Plan
    current_state_name: str
    step_execution_counts: dict[str, int] = field(default_factory=dict)
    similar_plan_count: int = 0
    awm: Any = None  # Working memory instance

    def record_step_execution(self, step_id: str) -> None:
        """Increment the execution count for *step_id*."""
        self.step_execution_counts[step_id] = self.step_execution_counts.get(step_id, 0) + 1

    def step_executions(self, step_id: str) -> int:
        """Return how many times *step_id* has been executed."""
        return self.step_execution_counts.get(step_id, 0)

    def is_step_stuck(self, step_id: str, max_repetitions: int = 3) -> bool:
        """Return True if *step_id* has been executed too many times."""
        return self.step_executions(step_id) >= max_repetitions
