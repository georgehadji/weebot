"""BenchmarkRunner — runs WeebotTask samples through a PlanActFlow.

The runner accepts a *flow_factory* callable (Session -> BaseFlow) so it
never imports PlanActFlow directly, keeping the dependency direction clean:
Application harness → Domain models only. PlanActFlow is injected by the DI
container (same pattern as SkillOptFlow._target_flow_factory).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from weebot.domain.models.benchmark_task import WeebotTask
from weebot.domain.models.session import Session
from weebot.domain.models.trajectory import TrajectorySummary
from weebot.application.harness.scorer import TaskScorer

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Result of running one (task, sample) pair."""
    task_id: str
    sample_idx: int
    score: float
    passed: bool
    answer: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "sample_idx": self.sample_idx,
            "score": self.score,
            "passed": self.passed,
            "answer": self.answer,
            "error": self.error,
        }


class BenchmarkRunner:
    """Runs benchmark tasks through weebot's PlanActFlow and scores results.

    Args:
        flow_factory: Callable[Session] -> BaseFlow. Typically
            ``container._create_target_flow_factory()``.
        scorer: TaskScorer instance (stateless, shareable).
        skill_name: Stored in TrajectorySummary.skill_name.
        skill_version: Stored in TrajectorySummary.skill_version.
    """

    def __init__(
        self,
        flow_factory: Callable,
        scorer: Optional[TaskScorer] = None,
        skill_name: str = "general",
        skill_version: int = 0,
    ) -> None:
        self._flow_factory = flow_factory
        self._scorer = scorer or TaskScorer()
        self._skill_name = skill_name
        self._skill_version = skill_version

    async def run_task(
        self,
        task: WeebotTask,
        sample_idx: int = 0,
    ) -> BenchmarkResult:
        """Run one sample from *task* and return a scored BenchmarkResult."""
        if sample_idx >= len(task.samples):
            return BenchmarkResult(
                task_id=task.task_id,
                sample_idx=sample_idx,
                score=0.0,
                passed=False,
                error=f"sample_idx {sample_idx} out of range (task has {len(task.samples)} samples)",
            )

        sample = task.samples[sample_idx]
        session_id = f"{task.task_id}-{sample_idx}-{uuid.uuid4().hex[:8]}"
        session = Session(
            id=session_id,
            user_id="benchmark",
            agent_id="benchmark-runner",
            context={
                "skill_name": self._skill_name,
                "skill_version": self._skill_version,
            },
        )

        try:
            flow = self._flow_factory(session)
            async for _ in flow.run(sample.prompt):
                pass
        except Exception as exc:
            logger.warning("Flow failed for task %s sample %d: %s", task.task_id, sample_idx, exc)
            return BenchmarkResult(
                task_id=task.task_id,
                sample_idx=sample_idx,
                score=0.0,
                passed=False,
                error=str(exc),
            )

        try:
            score = await self._scorer.score(session, task, sample_idx)
        except Exception as exc:
            logger.warning("Scoring failed for task %s sample %d: %s", task.task_id, sample_idx, exc)
            score = 0.0

        answer = TaskScorer._extract_answer(session)
        return BenchmarkResult(
            task_id=task.task_id,
            sample_idx=sample_idx,
            score=score,
            passed=score >= task.pass_threshold,
            answer=answer,
        )

    async def run_batch(
        self,
        tasks: List[WeebotTask],
        concurrency: int = 4,
    ) -> List[BenchmarkResult]:
        """Run all samples from all *tasks* with bounded concurrency.

        Args:
            tasks: List of WeebotTask to execute.
            concurrency: Maximum number of concurrent flow executions.

        Returns:
            Flat list of BenchmarkResult, one per (task, sample) pair.
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _run_one(task: WeebotTask, idx: int) -> BenchmarkResult:
            async with semaphore:
                return await self.run_task(task, idx)

        coros = [
            _run_one(task, idx)
            for task in tasks
            for idx in range(len(task.samples))
        ]
        return list(await asyncio.gather(*coros))

    async def run_to_trajectory(
        self,
        task: WeebotTask,
        sample_idx: int = 0,
    ) -> TrajectorySummary:
        """Run one sample and return a TrajectorySummary for the optimizer."""
        result = await self.run_task(task, sample_idx)

        sample = task.samples[sample_idx] if sample_idx < len(task.samples) else None
        expected = sample.expected_answer if sample else None

        return TrajectorySummary(
            task_id=f"{task.task_id}[{sample_idx}]",
            session_id=f"{task.task_id}-{sample_idx}",
            skill_name=self._skill_name,
            skill_version=self._skill_version,
            harness="weebot_benchmark",
            score=result.score,
            passed=result.passed,
            failure_modes=["benchmark_failure"] if not result.passed else [],
            success_patterns=["benchmark_pass"] if result.passed else [],
            tool_call_count=0,
            total_tokens=0,
            total_cost=0.0,
            trajectory_text=result.answer or "",
            answer=result.answer,
            expected_answer=expected,
        )
