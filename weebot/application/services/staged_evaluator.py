"""StagedEvaluator — probe-then-full evaluation for SkillOptFlow (HyperAgents Enhancement 2).

Matching the DGM-H paper's staged evaluation protocol: each agent is first
tested on a small probe subset.  Only agents with sufficient probe performance
advance to full evaluation.  This dramatically reduces compute cost.

Default: probe_size=10, threshold=0.3
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class StagedResult:
    """Result of a staged evaluation."""

    score: float
    probe_score: float
    full_score: float | None  # None if probe was below threshold
    remaining_assumed_zero: bool
    tasks_evaluated: int
    tasks_skipped: int


class StagedEvaluator:
    """Two-phase evaluator: probe → full.

    Usage:
        evaluator = StagedEvaluator(probe_size=10, threshold=0.3)

        async def eval_fn(agent, tasks: list) -> float:
            ...  # returns 0..1 score

        result = await evaluator.evaluate(agent, all_tasks, eval_fn)
    """

    def __init__(self, probe_size: int = 10, threshold: float = 0.3):
        if probe_size < 1:
            raise ValueError("probe_size must be >= 1")
        if not (0.0 <= threshold <= 1.0):
            raise ValueError("threshold must be in [0.0, 1.0]")
        self.probe_size = probe_size
        self.threshold = threshold

    async def evaluate(
        self,
        agent: Any,
        tasks: list[Any],
        eval_fn: Callable[[Any, list[Any]], float],
    ) -> StagedResult:
        """Evaluate *agent* on *tasks* with probe-then-full strategy.

        Args:
            agent: The agent/tool being evaluated.
            tasks: Complete list of evaluation tasks.
            eval_fn: Async callable (agent, task_subset) -> score (0..1).

        Returns:
            StagedResult with scores and evaluation statistics.
        """
        total = len(tasks)
        if total <= self.probe_size:
            # Not enough tasks to stage — evaluate all
            full_score = await eval_fn(agent, tasks)
            return StagedResult(
                score=full_score,
                probe_score=full_score,
                full_score=full_score,
                remaining_assumed_zero=False,
                tasks_evaluated=total,
                tasks_skipped=0,
            )

        # Phase 1: probe
        probe_tasks = tasks[:self.probe_size]
        probe_score = await eval_fn(agent, probe_tasks)

        if probe_score < self.threshold:
            # Below threshold — skip full evaluation, assume zero
            return StagedResult(
                score=probe_score,
                probe_score=probe_score,
                full_score=None,
                remaining_assumed_zero=True,
                tasks_evaluated=self.probe_size,
                tasks_skipped=total - self.probe_size,
            )

        # Phase 2: full evaluation
        full_score = await eval_fn(agent, tasks)
        return StagedResult(
            score=full_score,
            probe_score=probe_score,
            full_score=full_score,
            remaining_assumed_zero=False,
            tasks_evaluated=total,
            tasks_skipped=0,
        )
