"""RegressionGate — validates harness candidates against held-in and held-out splits.

Implements the paper's acceptance rule:
  Δ_in ≥ 0 AND Δ_ho ≥ 0 AND max(Δ_in, Δ_ho) > 0

Progressive validation (cost-aware):
  1. Run held-in tasks under both harness → Δ_in
  2. If Δ_in < 0 → REJECT (skip held-out, saves cost)
  3. Run held-out tasks under both harness → Δ_ho
  4. Apply acceptance rule

The gate is decoupled from task execution via a ``task_runner`` callable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from weebot.config.harness.schema import HarnessConfig
from weebot.domain.models.harness_edit import PromotionDecision
from weebot.domain.models.benchmark_task import WeebotTask

logger = logging.getLogger(__name__)


@dataclass
class TaskRunReport:
    """Summary of running a set of tasks under one harness config."""

    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_results(cls, results: list[dict]) -> "TaskRunReport":
        """Build a report from task-run result dicts.

        Each dict must have at least:
          - ``passed``: bool
          - ``error``: str (optional)
        """
        total = len(results)
        passed = sum(1 for r in results if r.get("passed", False))
        errors = [r.get("error", "") for r in results if r.get("error")]
        return cls(
            total=total,
            passed=passed,
            pass_rate=passed / total if total > 0 else 0.0,
            errors=errors,
        )


class RegressionGate:
    """Validates harness candidates through progressive regression testing.

    The gate uses a ``task_runner`` callable to evaluate tasks under a
    specific ``HarnessConfig``.  The runner is injected by the caller
    (``HarnessOptFlow`` or DI), keeping the gate decoupled from how
    PlanActFlow is instantiated.

    Usage::

        async def run_tasks(tasks: list[WeebotTask], config: HarnessConfig
                            ) -> list[dict]:
            # ... create PlanActFlow with config, run tasks, score ...
            return [{"passed": True}, ...]

        gate = RegressionGate(task_runner=run_tasks)
        decision = await gate.validate(baseline, candidate, held_in, held_out)
    """

    def __init__(
        self,
        task_runner: Optional[Callable] = None,
    ):
        """Initialize the gate.

        Args:
            task_runner: Async callable ``(tasks: list[WeebotTask],
                config: HarnessConfig) -> list[dict]``.  Each result dict
                must have a ``"passed": bool`` key.  When None (test mode),
                the gate uses a stub that always returns ``passed=True``.
        """
        self._task_runner = task_runner

    async def validate(
        self,
        baseline: Any,
        candidate: Any,
        held_in_tasks: Optional[list[str]] = None,
        held_out_tasks: Optional[list[str]] = None,
        repeats: int = 2,
    ) -> PromotionDecision:
        """Progressive validation with early rejection.

        Args:
            baseline: Current ``HarnessConfig``.
            candidate: Proposed candidate ``HarnessConfig``.
            held_in_tasks: Task IDs for measuring improvement.
            held_out_tasks: Task IDs for regression detection.
            repeats: Number of repeated runs (for stochastic stability).

        Returns:
            ``PromotionDecision``.
        """
        if self._task_runner is None:
            # Test mode — always accept
            logger.info("RegressionGate: no task_runner — auto-accepting")
            return PromotionDecision(
                accepted=True,
                delta_in=0.0,
                delta_ho=0.0,
                reason="No task_runner configured — auto-accepted",
            )

        held_in_tasks = held_in_tasks or []
        held_out_tasks = held_out_tasks or []

        # ── Phase 1: held-in evaluation ───────────────────────────────
        logger.info(
            "RegressionGate: evaluating %d held-in tasks (baseline vs candidate)",
            len(held_in_tasks),
        )

        baseline_in_report, candidate_in_report = await self._run_split(
            tasks=held_in_tasks,
            baseline=baseline,
            candidate=candidate,
            repeats=repeats,
        )

        delta_in = candidate_in_report.pass_rate - baseline_in_report.pass_rate

        if delta_in < 0:
            reason = (
                f"Held-in regression: baseline {baseline_in_report.pass_rate:.1%} "
                f"→ candidate {candidate_in_report.pass_rate:.1%} "
                f"(Δ_in={delta_in:+.2f} < 0)"
            )
            logger.warning(reason)
            return PromotionDecision(
                accepted=False,
                delta_in=delta_in,
                delta_ho=0.0,
                reason=reason,
            )

        # ── Phase 2: held-out evaluation ──────────────────────────────
        logger.info(
            "RegressionGate: held-in OK (Δ_in=%+.2f), "
            "evaluating %d held-out tasks",
            delta_in, len(held_out_tasks),
        )

        baseline_ho_report, candidate_ho_report = await self._run_split(
            tasks=held_out_tasks,
            baseline=baseline,
            candidate=candidate,
            repeats=repeats,
        )

        delta_ho = candidate_ho_report.pass_rate - baseline_ho_report.pass_rate

        # ── Apply acceptance rule ─────────────────────────────────────
        if delta_ho < 0:
            reason = (
                f"Held-out regression: baseline {baseline_ho_report.pass_rate:.1%} "
                f"→ candidate {candidate_ho_report.pass_rate:.1%} "
                f"(Δ_ho={delta_ho:+.2f} < 0)"
            )
            logger.warning(reason)
            return PromotionDecision(
                accepted=False,
                delta_in=delta_in,
                delta_ho=delta_ho,
                reason=reason,
            )

        if delta_in <= 0 and delta_ho <= 0:
            reason = (
                f"No improvement: Δ_in={delta_in:+.2f}, Δ_ho={delta_ho:+.2f}"
            )
            logger.info(reason)
            return PromotionDecision(
                accepted=False,
                delta_in=delta_in,
                delta_ho=delta_ho,
                reason=reason,
            )

        reason = (
            f"Held-in: {baseline_in_report.pass_rate:.1%}→{candidate_in_report.pass_rate:.1%} "
            f"(Δ_in={delta_in:+.2f}), "
            f"Held-out: {baseline_ho_report.pass_rate:.1%}→{candidate_ho_report.pass_rate:.1%} "
            f"(Δ_ho={delta_ho:+.2f})"
        )
        logger.info("RegressionGate: ACCEPT — %s", reason)
        return PromotionDecision(
            accepted=True,
            delta_in=delta_in,
            delta_ho=delta_ho,
            reason=reason,
        )

    # ── Internal: run one split (held-in or held-out) ─────────────────

    async def _run_split(
        self,
        tasks: list[str],
        baseline: Any,
        candidate: Any,
        repeats: int,
    ) -> tuple[TaskRunReport, TaskRunReport]:
        """Run both baseline and candidate on *tasks*, return (baseline, candidate) reports.

        Aggregates across ``repeats`` runs for stochastic stability.
        """
        # Convert task IDs to WeebotTasks
        weebot_tasks = [WeebotTask(task_id=tid, description="", samples=[])
                        for tid in tasks]

        # Baseline runs
        all_baseline_results = []
        for _ in range(repeats):
            results = await self._task_runner(weebot_tasks, baseline)
            all_baseline_results.extend(results)

        # Candidate runs
        all_candidate_results = []
        for _ in range(repeats):
            results = await self._task_runner(weebot_tasks, candidate)
            all_candidate_results.extend(results)

        baseline_report = TaskRunReport.from_results(all_baseline_results)
        candidate_report = TaskRunReport.from_results(all_candidate_results)

        return baseline_report, candidate_report
