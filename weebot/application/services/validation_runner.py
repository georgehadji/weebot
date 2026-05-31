"""Validation runner — evaluates a candidate skill against held-out tasks.

Runs the target model on validation tasks with the candidate skill,
compares the average score against the current best skill's score,
and decides acceptance or rejection.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.session import Session

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of a validation gate evaluation.

    Attributes:
        passed: True when candidate_score > current_score (ties are rejected).
        candidate_score: Average score of the candidate skill on validation tasks.
        current_score: Average score of the current best skill.
        score_delta: candidate_score - current_score (positive = improvement).
        n_tasks: Number of validation tasks that completed.
    """

    def __init__(
        self,
        passed: bool,
        candidate_score: float,
        current_score: float,
        n_tasks: int,
        details: Optional[dict[str, Any]] = None,
    ):
        self.passed = passed
        self.candidate_score = candidate_score
        self.current_score = current_score
        self.score_delta = candidate_score - current_score
        self.n_tasks = n_tasks
        self.details = details or {}

    def __repr__(self) -> str:
        delta = f"+{self.score_delta:.3f}" if self.score_delta >= 0 else f"{self.score_delta:.3f}"
        status = "ACCEPTED" if self.passed else "REJECTED"
        return (
            f"ValidationResult({status}, Δ={delta}, "
            f"candidate={self.candidate_score:.3f}, "
            f"current={self.current_score:.3f}, "
            f"n={self.n_tasks})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "candidate_score": self.candidate_score,
            "current_score": self.current_score,
            "score_delta": self.score_delta,
            "n_tasks": self.n_tasks,
            "details": self.details,
        }


class ValidationRunner:
    """Validates candidate skills against held-out tasks.

    The validation runner does NOT modify the skill or the task runner's
    state.  It creates temporary sessions, runs them to completion, and
    returns a pass/fail decision.
    """

    def __init__(
        self,
        task_runner: TaskRunner,
        flow_factory: Callable,
        scoring_fn: Callable,
    ):
        """
        Args:
            task_runner: For executing validation tasks.
            flow_factory: Factory that creates flows with a given skill context.
            scoring_fn: Function that scores a completed session (0.0–1.0).
        """
        self._task_runner = task_runner
        self._flow_factory = flow_factory
        self._scoring_fn = scoring_fn

    async def validate(
        self,
        candidate_content: str,
        validation_task_ids: list[str],
        harness: str = "direct_chat",
        baseline_score: Optional[float] = None,
    ) -> ValidationResult:
        """Evaluate the candidate skill on held-out tasks.

        Args:
            candidate_content: The candidate skill markdown content.
            validation_task_ids: Task descriptions/prompts for validation.
            harness: Execution harness identifier.
            baseline_score: Current best score to compare against.
                If None, tasks are run without a baseline and the result
                is always accepted (first-version bootstrap).

        Returns:
            ValidationResult with pass/fail decision.
        """
        if not validation_task_ids:
            return ValidationResult(
                passed=True,
                candidate_score=0.0,
                current_score=baseline_score or 0.0,
                n_tasks=0,
                details={"message": "No validation tasks — skipping"},
            )

        # Run all validation tasks in parallel
        async def run_task(task_id: str) -> float:
            """Run a single validation task and return its score."""
            session = Session(
                id=f"val-{task_id}",
                user_id="skillopt",
                agent_id="validation-runner",
                context={
                    "skill_name": "validation",
                    "skill_content": candidate_content,
                    "last_prompt": task_id,
                },
            )
            flow = self._flow_factory(session)
            try:
                async for _ in flow.run(task_id):
                    pass
                # PlanActFlow updates its own _session immutably — score that.
                completed = getattr(flow, "_session", session)
                return await self._scoring_fn(completed)
            except Exception as exc:
                logger.warning("Validation task '%s' failed: %s", task_id, exc)
                return 0.0

        tasks = [run_task(tid) for tid in validation_task_ids]
        scores = await asyncio.gather(*tasks)

        candidate_score = sum(scores) / len(scores) if scores else 0.0
        current_score = baseline_score if baseline_score is not None else candidate_score

        # Ties are rejected (paper §3.5)
        passed = candidate_score > current_score

        return ValidationResult(
            passed=passed,
            candidate_score=candidate_score,
            current_score=current_score,
            n_tasks=len(validation_task_ids),
            details={
                "harness": harness,
                "individual_scores": dict(zip(validation_task_ids, scores)),
            },
        )
