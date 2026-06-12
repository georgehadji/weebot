"""Phase 4 tests: RegressionGate progressive validation logic.

Tests the paper's acceptance rule, early rejection (cost savings),
and error handling.  Uses mocked task_runners to avoid real LLM calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from weebot.domain.models.harness_edit import PromotionDecision
from weebot.config.harness.schema import HarnessConfig


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_config(**overrides) -> HarnessConfig:
    """Create a HarnessConfig with optional instruction overrides."""
    cfg = HarnessConfig.default()
    if overrides:
        data = cfg.model_dump()
        data.update(overrides)
        cfg = HarnessConfig.model_validate(data)
    return cfg


async def _task_runner_all_pass(tasks, config):
    """Stub task runner: all tasks pass."""
    return [{"passed": True} for _ in tasks]


async def _task_runner_all_fail(tasks, config):
    """Stub task runner: all tasks fail."""
    return [{"passed": False} for _ in tasks]


async def _task_runner_mixed(tasks, config):
    """Stub task runner: first task fails, rest pass."""
    return [{"passed": False} if i == 0 else {"passed": True}
            for i in range(len(tasks))]


# ── Acceptance Rule Tests ─────────────────────────────────────────────────

class TestRegressionGateAcceptance:
    """Tests for the paper's acceptance rule: Δ_in ≥ 0, Δ_ho ≥ 0, max > 0."""

    @pytest.mark.asyncio
    async def test_both_improve_accepts(self):
        from weebot.application.services.regression_gate import RegressionGate

        baseline = _make_config()
        candidate = _make_config(description="evolved")

        async def _runner(tasks, config):
            # Candidate always does better
            if config.description == "evolved":
                return [{"passed": True}] * len(tasks)
            return [{"passed": False}] * len(tasks)

        gate = RegressionGate(task_runner=_runner)
        decision = await gate.validate(
            baseline=baseline,
            candidate=candidate,
            held_in_tasks=["task1", "task2"],
            held_out_tasks=["task3", "task4"],
            repeats=1,
        )
        assert decision.accepted, (
            f"Both splits improved but gate rejected: {decision.reason}"
        )
        assert decision.delta_in > 0
        assert decision.delta_ho > 0

    @pytest.mark.asyncio
    async def test_held_in_regression_rejects_early(self):
        """If Δ_in < 0, gate should reject WITHOUT running held-out."""
        from weebot.application.services.regression_gate import RegressionGate

        baseline = _make_config()
        candidate = _make_config(description="worse")

        call_log = {"held_out_ran": False}

        async def _runner(tasks, config):
            # Candidate does worse on all tasks
            if config.description == "worse":
                return [{"passed": False}] * len(tasks)
            return [{"passed": True}] * len(tasks)

        original_run_split = RegressionGate._run_split
        try:
            # Track whether held-out would have run
            async def tracking_run_split(self, tasks, baseline, candidate, repeats):
                held_in = ["held-in"]
                held_out = ["held-out"]

                # Determine which split we're running based on tasks
                if tasks and tasks[0] == "held-out":
                    call_log["held_out_ran"] = True

                return await original_run_split(self, tasks, baseline, candidate, repeats)

            RegressionGate._run_split = tracking_run_split
            gate = RegressionGate(task_runner=_runner)
            decision = await gate.validate(
                baseline=baseline,
                candidate=candidate,
                held_in_tasks=["held-in"],
                held_out_tasks=["held-out"],
                repeats=1,
            )
            assert not decision.accepted
            assert decision.delta_in < 0
            assert decision.delta_ho == 0.0  # Held-out was never computed
        finally:
            RegressionGate._run_split = original_run_split

    @pytest.mark.asyncio
    async def test_held_out_regression_rejects(self):
        """If Δ_in ≥ 0 but Δ_ho < 0, gate rejects."""
        from weebot.application.services.regression_gate import RegressionGate

        baseline = _make_config()
        candidate = _make_config(description="overfit")

        async def _runner(tasks, config):
            # Candidate is same or better on held-in, worse on held-out
            if config.description == "overfit":
                # This runs BOTH held-in and held-out
                return [{"passed": True}] * len(tasks)
            return [{"passed": False}] * len(tasks)

        # We need to simulate: baseline worse on held-in, better on held-out
        # Actually, let me use a different approach: track which split we're on

        class _TrackingRunner:
            def __init__(self):
                self._called = 0
            async def __call__(self, tasks, config):
                self._called += 1
                # 1st call (baseline held-in): worse
                # 2nd call (candidate held-in): better → Δ_in > 0
                # 3rd call (baseline held-out): better
                # 4th call (candidate held-out): worse → Δ_ho < 0
                if self._called % 2 == 0:  # Candidate (even call: 2, 4)
                    if self._called == 2:  # candidate held-in → pass
                        return [{"passed": True}] * len(tasks)
                    else:  # self._called == 4: candidate held-out → fail
                        return [{"passed": False}] * len(tasks)
                else:  # Baseline (odd call: 1, 3)
                    if self._called == 1:  # baseline held-in → fail
                        return [{"passed": False}] * len(tasks)
                    else:  # self._called == 3: baseline held-out → pass
                        return [{"passed": True}] * len(tasks)

        gate = RegressionGate(task_runner=_TrackingRunner())
        decision = await gate.validate(
            baseline=baseline,
            candidate=candidate,
            held_in_tasks=["hi1", "hi2"],
            held_out_tasks=["ho1", "ho2"],
            repeats=1,
        )
        assert not decision.accepted, (
            f"Δ_ho should be negative but gate accepted: {decision.reason}"
        )
        assert decision.delta_ho < 0

    @pytest.mark.asyncio
    async def test_no_improvement_rejects(self):
        """If Δ_in = 0 and Δ_ho = 0, gate rejects."""
        from weebot.application.services.regression_gate import RegressionGate

        gate = RegressionGate(task_runner=_task_runner_all_pass)
        decision = await gate.validate(
            baseline=_make_config(),
            candidate=_make_config(),
            held_in_tasks=["a", "b"],
            held_out_tasks=["c"],
            repeats=1,
        )
        # Both runner and candidate return same results, so Δ = 0
        assert not decision.accepted
        assert "No improvement" in decision.reason

    @pytest.mark.asyncio
    async def test_no_task_runner_auto_accepts(self):
        """When no task_runner is set, gate auto-accepts (test mode)."""
        from weebot.application.services.regression_gate import RegressionGate

        gate = RegressionGate()
        decision = await gate.validate(
            baseline=_make_config(),
            candidate=_make_config(),
        )
        assert decision.accepted
        assert "No task_runner" in decision.reason


# ── TaskRunReport Tests ──────────────────────────────────────────────────

class TestTaskRunReport:
    def test_from_results_all_pass(self):
        from weebot.application.services.regression_gate import TaskRunReport
        report = TaskRunReport.from_results([
            {"passed": True},
            {"passed": True},
        ])
        assert report.total == 2
        assert report.passed == 2
        assert report.pass_rate == 1.0

    def test_from_results_some_fail(self):
        from weebot.application.services.regression_gate import TaskRunReport
        report = TaskRunReport.from_results([
            {"passed": True},
            {"passed": False},
        ])
        assert report.pass_rate == 0.5

    def test_from_results_with_errors(self):
        from weebot.application.services.regression_gate import TaskRunReport
        report = TaskRunReport.from_results([
            {"passed": False, "error": "timeout"},
        ])
        assert len(report.errors) == 1
        assert report.errors[0] == "timeout"

    def test_from_results_empty(self):
        from weebot.application.services.regression_gate import TaskRunReport
        report = TaskRunReport.from_results([])
        assert report.total == 0
        assert report.pass_rate == 0.0
