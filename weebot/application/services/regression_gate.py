"""RegressionGate — validates harness candidates against held-in and held-out splits.

Implements the paper's acceptance rule on a **composite metric** (not bare pass-rate):
  Δ_composite_in ≥ 0 AND Δ_composite_ho ≥ 0 AND max(Δ_in, Δ_ho) > 0

The composite metric is a weighted sum of all six HarnessMetrics dimensions,
computed by ``HarnessMetricScorer`` from per-task evaluation results.

Fail-closed default: if no ``task_runner`` is provided, the gate **rejects**
the candidate.  Test callers must inject a stub runner explicitly.

Changes from v1:
- ``task_runner`` returns ``{"passed": bool, "metrics": HarnessMetrics}`` per task.
- ``PromotionDecision`` includes the composite delta (``delta_composite``).
- ``min_held_out_tasks`` configurable floor (default 2).
- ``auto_accept`` explicit opt-in for legacy callers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from weebot.config.harness.schema import HarnessConfig
from weebot.domain.models.harness_edit import PromotionDecision
from weebot.domain.models.harness_metrics import HarnessMetrics

logger = logging.getLogger(__name__)

# Default composite weights (from HarnessMetrics.composite)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "task_pass_rate": 2.0,
    "verification_strength": 2.0,
    "trajectory_efficiency": 1.0,
    "recovery_ability": 1.0,
    "state_consistency": 0.5,
    "replayability": 0.5,
}


@dataclass
class TaskRunReport:
    """Summary of running a set of tasks under one harness config."""

    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    composite_score: float = 0.0
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_results(
        cls,
        results: list[dict],
        weights: Optional[dict[str, float]] = None,
    ) -> "TaskRunReport":
        """Build a report from task-run result dicts.

        Each dict must have at least:
          - ``passed``: bool
          - ``metrics``: ``HarnessMetrics`` dict (optional — uses defaults if missing)
          - ``error``: str (optional)
        """
        total = len(results)
        passed = sum(1 for r in results if r.get("passed", False))
        errors = [r.get("error", "") for r in results if r.get("error")]

        # Aggregate metrics from all tasks
        all_metrics = []
        for r in results:
            metrics_data = r.get("metrics")
            if metrics_data:
                try:
                    if isinstance(metrics_data, dict):
                        all_metrics.append(HarnessMetrics(**metrics_data))
                    else:
                        all_metrics.append(metrics_data)
                except (TypeError, ValueError):
                    all_metrics.append(HarnessMetrics(task_pass_rate=1.0 if r.get("passed") else 0.0))
            else:
                all_metrics.append(HarnessMetrics(task_pass_rate=1.0 if r.get("passed") else 0.0))

        # Compute average composite score
        if all_metrics:
            avg_composite = sum(
                m.composite(weights=weights) for m in all_metrics
            ) / len(all_metrics)
        else:
            avg_composite = 0.0

        return cls(
            total=total,
            passed=passed,
            pass_rate=passed / total if total > 0 else 0.0,
            composite_score=avg_composite,
            errors=errors,
        )


class RegressionGate:
    """Validates harness candidates through progressive regression testing.

    Usage::

        async def run_tasks(task_ids: list[str], config: HarnessConfig
                            ) -> list[dict]:
            # ... create PlanActFlow with config, run tasks, score ...
            return [{"passed": True, "metrics": {...}}, ...]

        gate = RegressionGate(task_runner=run_tasks)
        decision = await gate.validate(baseline, candidate, held_in, held_out)
    """

    def __init__(
        self,
        task_runner: Optional[Callable] = None,
        *,
        auto_accept: bool = False,
        min_held_out_tasks: int = 2,
        composite_weights: Optional[dict[str, float]] = None,
    ):
        """Initialize the gate.

        Args:
            task_runner: Async callable ``(task_ids: list[str],
                config: HarnessConfig) -> list[dict]``.  Each result dict
                must have ``"passed": bool`` and may have ``"metrics"``
                (HarnessMetrics or dict).
            auto_accept: If True and no task_runner, auto-accept (legacy compat).
                Default False — fail-closed.
            min_held_out_tasks: Minimum held-out tasks required for a valid
                evaluation.  Below this floor, the candidate is rejected.
            composite_weights: Override for the composite metric weights.
        """
        self._task_runner = task_runner
        self._auto_accept = auto_accept
        self._min_held_out_tasks = min_held_out_tasks
        self._weights = composite_weights or _DEFAULT_WEIGHTS

    # ── Public API ─────────────────────────────────────────────────

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
            if self._auto_accept:
                logger.info("RegressionGate: no task_runner + auto_accept — accepting")
                return PromotionDecision(
                    accepted=True,
                    delta_in=0.0,
                    delta_ho=0.0,
                    reason="No task_runner + auto_accept — accepted",
                )
            # Fail-closed
            logger.warning("RegressionGate: no task_runner — REJECTING (fail-closed)")
            return PromotionDecision(
                accepted=False,
                delta_in=0.0,
                delta_ho=0.0,
                reason="No task_runner configured — rejected (fail-closed)",
            )

        held_in_tasks = held_in_tasks or []
        held_out_tasks = held_out_tasks or []

        # ── Phase 0: sanity checks ────────────────────────────────
        if len(held_out_tasks) < self._min_held_out_tasks:
            reason = (
                f"Too few held-out tasks ({len(held_out_tasks)} < "
                f"{self._min_held_out_tasks}) — rejecting"
            )
            logger.warning(reason)
            return PromotionDecision(
                accepted=False,
                delta_in=0.0,
                delta_ho=0.0,
                reason=reason,
            )

        # ── Phase 1: held-in evaluation ───────────────────────────
        logger.info(
            "RegressionGate: evaluating %d held-in tasks (baseline vs candidate)",
            len(held_in_tasks),
        )

        baseline_in_report, candidate_in_report = await self._run_split(
            task_ids=held_in_tasks,
            baseline=baseline,
            candidate=candidate,
            repeats=repeats,
        )

        # Composite delta (primary signal)
        delta_composite_in = (
            candidate_in_report.composite_score - baseline_in_report.composite_score
        )
        # Pass-rate delta (secondary signal, kept for backward compat)
        delta_in = candidate_in_report.pass_rate - baseline_in_report.pass_rate

        if delta_composite_in < 0:
            reason = (
                f"Held-in regression: baseline composite "
                f"{baseline_in_report.composite_score:.4f} → "
                f"candidate {candidate_in_report.composite_score:.4f} "
                f"(Δ_composite={delta_composite_in:+.4f} < 0)"
            )
            logger.warning(reason)
            return PromotionDecision(
                accepted=False,
                delta_in=delta_in,
                delta_ho=0.0,
                reason=reason,
            )

        # ── Phase 2: held-out evaluation ──────────────────────────
        logger.info(
            "RegressionGate: held-in OK (Δ_composite=%+.4f), "
            "evaluating %d held-out tasks",
            delta_composite_in, len(held_out_tasks),
        )

        baseline_ho_report, candidate_ho_report = await self._run_split(
            task_ids=held_out_tasks,
            baseline=baseline,
            candidate=candidate,
            repeats=repeats,
        )

        delta_composite_ho = (
            candidate_ho_report.composite_score - baseline_ho_report.composite_score
        )
        delta_ho = candidate_ho_report.pass_rate - baseline_ho_report.pass_rate

        # ── Apply acceptance rule on composite ────────────────────
        if delta_composite_ho < 0:
            reason = (
                f"Held-out regression: baseline composite "
                f"{baseline_ho_report.composite_score:.4f} → "
                f"candidate {candidate_ho_report.composite_score:.4f} "
                f"(Δ_composite_ho={delta_composite_ho:+.4f} < 0)"
            )
            logger.warning(reason)
            return PromotionDecision(
                accepted=False,
                delta_in=delta_in,
                delta_ho=delta_ho,
                reason=reason,
            )

        if delta_composite_in <= 0 and delta_composite_ho <= 0:
            reason = (
                f"No improvement: Δ_composite_in={delta_composite_in:+.4f}, "
                f"Δ_composite_ho={delta_composite_ho:+.4f}"
            )
            logger.info(reason)
            return PromotionDecision(
                accepted=False,
                delta_in=delta_in,
                delta_ho=delta_ho,
                reason=reason,
            )

        reason = (
            f"ACCEPT — Held-in composite: "
            f"{baseline_in_report.composite_score:.4f}→{candidate_in_report.composite_score:.4f} "
            f"(Δ_composite={delta_composite_in:+.4f}), "
            f"Held-out composite: "
            f"{baseline_ho_report.composite_score:.4f}→{candidate_ho_report.composite_score:.4f} "
            f"(Δ_composite={delta_composite_ho:+.4f})"
        )
        logger.info("RegressionGate: %s", reason)
        return PromotionDecision(
            accepted=True,
            delta_in=delta_in,
            delta_ho=delta_ho,
            reason=reason,
        )

    # ── Internal: run one split (held-in or held-out) ──────────────

    async def _run_split(
        self,
        task_ids: list[str],
        baseline: Any,
        candidate: Any,
        repeats: int,
    ) -> tuple[TaskRunReport, TaskRunReport]:
        """Run both baseline and candidate on *task_ids*, return reports.

        Aggregates across ``repeats`` runs for stochastic stability.
        """
        if not task_ids:
            return TaskRunReport(), TaskRunReport()

        # Baseline runs
        all_baseline_results: list[dict] = []
        for _ in range(repeats):
            results = await self._task_runner(task_ids, baseline)
            all_baseline_results.extend(results)

        # Candidate runs
        all_candidate_results: list[dict] = []
        for _ in range(repeats):
            results = await self._task_runner(task_ids, candidate)
            all_candidate_results.extend(results)

        baseline_report = TaskRunReport.from_results(
            all_baseline_results, weights=self._weights,
        )
        candidate_report = TaskRunReport.from_results(
            all_candidate_results, weights=self._weights,
        )

        return baseline_report, candidate_report
