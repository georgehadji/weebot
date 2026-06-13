"""EvalRunner — orchestrates evaluation tasks through judges.

The runner takes a task bank, calls the target (agent) for each task,
then scores each output through a judge. Results are aggregated into
a report with per-criterion breakdowns.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from weebot.application.ports.judge_port import CriterionScore, JudgePort, JudgeVerdict

logger = logging.getLogger(__name__)


@dataclass
class EvalTask:
    """A single evaluation task.

    Attributes:
        id: Unique task identifier.
        prompt: Input prompt to send to the agent.
        expected_output: Optional expected output for comparison.
        criteria: Criteria to evaluate against (e.g. ["correctness", "completeness"]).
    """
    id: str
    prompt: str
    expected_output: str = ""
    criteria: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Result of evaluating a single task.

    Attributes:
        task_id: ID of the evaluated task.
        score: Normalized 0.0–1.0 overall score.
        passed: Whether the output meets the pass threshold.
        judge_used: Class name of the judge used.
        reasoning: Summary reasoning from the judge.
        criteria: Per-criterion scores (if available).
    """
    task_id: str
    score: float
    passed: bool
    judge_used: str
    reasoning: str = ""
    criteria: list[CriterionScore] = field(default_factory=list)


@dataclass
class EvalReport:
    """Aggregated evaluation report across all tasks.

    Attributes:
        total: Total tasks evaluated.
        passed: Count of tasks that passed.
        pass_rate: Fraction of tasks that passed (0.0–1.0).
        avg_score: Mean score across all tasks.
        results: Per-task results.
        per_criterion: Per-criterion average scores, if criteria were used.
    """
    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    avg_score: float = 0.0
    results: list[EvalResult] = field(default_factory=list)
    per_criterion: dict[str, float] = field(default_factory=dict)


class EvalRunner:
    """Orchestrates evaluation: runs tasks through a target, scores via a judge.

    Args:
        judge: JudgePort implementation to score outputs.
        pass_threshold: Minimum score (0.0–1.0) for a task to pass.
    """

    def __init__(
        self,
        judge: JudgePort,
        pass_threshold: float = 0.6,
    ) -> None:
        self._judge = judge
        self._pass_threshold = pass_threshold

    async def run(
        self,
        target: Callable[[str], Any],
        tasks: list[EvalTask],
    ) -> EvalReport:
        """Run all tasks through *target* and score outputs via the judge.

        Args:
            target: Async callable that takes a prompt string and returns
                    the agent's output.
            tasks: List of EvalTask to evaluate.

        Returns:
            EvalReport with per-task and aggregate scores.
        """
        results: list[EvalResult] = []

        for task in tasks:
            try:
                output = await target(task.prompt)
                output_str = str(output) if output else "(no output)"
            except Exception as exc:
                logger.warning("Task %s failed during execution: %s", task.id, exc)
                output_str = f"(execution error: {exc})"

            try:
                verdict = await self._judge.judge(
                    task_description=task.prompt,
                    output=output_str,
                    criteria=task.criteria,
                    context=task.expected_output,
                )
            except Exception as exc:
                logger.warning("Judge failed for task %s: %s", task.id, exc)
                verdict = JudgeVerdict(
                    overall_score=0.0, passed=False,
                    reasoning=f"judge error: {exc}",
                )

            score = min(verdict.overall_score, 1.0)
            results.append(EvalResult(
                task_id=task.id,
                score=score,
                passed=score >= self._pass_threshold,
                judge_used=type(self._judge).__name__,
                reasoning=verdict.reasoning,
                criteria=verdict.criteria,
            ))

        # Aggregate
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        scores = [r.score for r in results]
        avg_score = sum(scores) / total if total > 0 else 0.0

        # Per-criterion aggregation
        per_criterion: dict[str, list[float]] = {}
        for r in results:
            for c in r.criteria:
                per_criterion.setdefault(c.name, []).append(c.score)
        per_criterion_avg = {
            name: sum(scores) / len(scores)
            for name, scores in per_criterion.items()
        }

        return EvalReport(
            total=total,
            passed=passed,
            pass_rate=passed / total if total > 0 else 0.0,
            avg_score=avg_score,
            results=results,
            per_criterion=per_criterion_avg,
        )
