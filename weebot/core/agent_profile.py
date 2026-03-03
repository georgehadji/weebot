"""AgentProfile — agent capability descriptor for Team-of-Thoughts orchestration.

Each profile declares *domain_expertise* keywords so the
:class:`WorkflowOrchestrator` can score which agent best fits a given task,
following the selective-activation pattern from the ToT paper.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class PerformanceRecord:
    """Accumulated performance metrics for an agent profile."""

    tasks_completed: int = 0
    tasks_failed: int = 0
    total_cost_usd: float = 0.0
    avg_latency_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        """Return success ratio (optimistic 1.0 when no data yet)."""
        total = self.tasks_completed + self.tasks_failed
        if total == 0:
            return 1.0
        return self.tasks_completed / total


@dataclass
class AgentProfile:
    """Describes an agent's capabilities, model preferences, and history.

    Scoring weights (class-level constants):
        - ``_ROLE_WEIGHT = 5.0``   — bonus when the role keyword appears in the task.
        - ``_EXPERTISE_WEIGHT = 3.0`` — proportional to expertise keyword overlap.
        - ``_PERFORMANCE_WEIGHT = 2.0`` — proportional to historical success rate.
    """

    role: str
    domain_expertise: List[str] = field(default_factory=list)
    preferred_model: str = ""
    performance: PerformanceRecord = field(default_factory=PerformanceRecord)
    max_steps: int = 30
    system_prompt_override: str = ""

    _ROLE_WEIGHT: float = 5.0
    _EXPERTISE_WEIGHT: float = 3.0
    _PERFORMANCE_WEIGHT: float = 2.0

    def match_score(self, task_description: str) -> float:
        """Score how well this profile matches *task_description*.

        Higher is better.  The score is the sum of:

        1. **Role keyword match** — ``_ROLE_WEIGHT`` if the role name
           appears as a substring (case-insensitive).
        2. **Expertise overlap** — ``_EXPERTISE_WEIGHT × (matched / total)``
           where *matched* is the count of expertise keywords found.
        3. **Performance bonus** — ``_PERFORMANCE_WEIGHT × success_rate``.
        """
        desc_lower = task_description.lower()
        score = 0.0

        # 1. Role keyword match
        if self.role.lower() in desc_lower:
            score += self._ROLE_WEIGHT

        # 2. Expertise overlap
        if self.domain_expertise:
            matched = sum(
                1 for kw in self.domain_expertise if kw.lower() in desc_lower
            )
            score += self._EXPERTISE_WEIGHT * (matched / len(self.domain_expertise))

        # 3. Performance bonus
        score += self._PERFORMANCE_WEIGHT * self.performance.success_rate

        return score

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_completion(self, cost_usd: float, latency_seconds: float) -> None:
        """Record a successful task completion."""
        p = self.performance
        total_prev = p.tasks_completed + p.tasks_failed
        p.tasks_completed += 1
        # Running average for latency
        if total_prev > 0:
            p.avg_latency_seconds = (
                p.avg_latency_seconds * total_prev + latency_seconds
            ) / (total_prev + 1)
        else:
            p.avg_latency_seconds = latency_seconds
        p.total_cost_usd += cost_usd

    def record_failure(self) -> None:
        """Record a task failure."""
        self.performance.tasks_failed += 1
