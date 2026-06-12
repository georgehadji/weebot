"""Phase 4 tests: RegressionGate progressive validation logic.

Tests the paper's acceptance rule, early rejection (cost savings),
and error handling.  Uses mocked task_runners to avoid real LLM calls.
"""
from __future__ import annotations

import pytest

from weebot.domain.models.harness_edit import PromotionDecision
from weebot.config.harness.schema import HarnessConfig


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_config(**overrides) -> HarnessConfig:
    """Create a HarnessConfig with optional field overrides."""
    cfg = HarnessConfig.default()
    if overrides:
        data = cfg.model_dump()
        data.update(overrides)
        cfg = HarnessConfig.model_validate(data)
    return cfg


async def _task_runner_all_pass(task_ids, config):
    """All tasks pass regardless of config."""
    return [{"passed": True} for _ in task_ids]


async def _task_runner_all_fail(task_ids, config):
    """All tasks fail regardless of config."""
    return [{"passed": False} for _ in task_ids]


# ── Acceptance Rule Tests ─────────────────────────────────────────────────

class TestRegressionGateAcceptance:
    """Tests for the paper's rule: Δ_in ≥ 0, Δ_ho ≥ 0, max(Δ_in, Δ_ho) > 0."""

    @pytest.mark.asyncio
    async def test_both_improve_accepts(self):
        """Candidate better on both splits → ACCEPT."""
        from weebot.application.services.regression_gate import RegressionGate

        baseline = _make_config()
        candidate = _make_config(description="evolved")

        async def _runner(task_ids, config):
            if config.description == "evolved":
                return [{"passed": True}] * len(task_ids)
            return [{"passed": False}] * len(task_ids)

        gate = RegressionGate(task_runner=_runner)
        decision = await gate.validate(
            baseline=baseline,
            candidate=candidate,
            held_in_tasks=["t1", "t2"],
            held_out_tasks=["t3", "t4"],
            repeats=1,
        )
        assert decision.accepted
        assert decision.delta_in > 0
        assert decision.delta_ho > 0

    @pytest.mark.asyncio
    async def test_held_in_regression_rejects_early(self):
        """If Δ_in < 0, gate rejects without evaluating held-out."""
        from weebot.application.services.regression_gate import RegressionGate

        baseline = _make_config()
        candidate = _make_config(description="worse")
        call_count = {"n": 0}

        async def _runner(task_ids, config):
            call_count["n"] += 1
            # Candidate fails everything; baseline passes everything
            if config.description == "worse":
                return [{"passed": False}] * len(task_ids)
            return [{"passed": True}] * len(task_ids)

        gate = RegressionGate(task_runner=_runner)
        decision = await gate.validate(
            baseline=baseline,
            candidate=candidate,
            held_in_tasks=["hi"],
            held_out_tasks=["ho"],
            repeats=1,
        )
        assert not decision.accepted
        assert decision.delta_in < 0
        assert decision.delta_ho == 0.0  # Never computed
        # task_runner called 2 times (baseline held-in + candidate held-in)
        # NOT 4 times (which would mean held-out also ran)
        assert call_count["n"] == 2, (
            f"Expected 2 calls (held-in only) but got {call_count['n']}"
        )

    @pytest.mark.asyncio
    async def test_held_out_regression_rejects(self):
        """If Δ_in ≥ 0 but Δ_ho < 0, gate rejects."""
        from weebot.application.services.regression_gate import RegressionGate

        baseline = _make_config(description="baseline")
        candidate = _make_config(description="overfit")

        async def _runner(task_ids, config):
            is_candidate = config.description == "overfit"
            # Distinguish held-in vs held-out by task ID prefix
            is_held_out = any(tid.startswith("ho") for tid in task_ids)

            if is_candidate and not is_held_out:
                # Candidate improves on held-in
                return [{"passed": True}] * len(task_ids)
            elif is_candidate and is_held_out:
                # Candidate regresses on held-out
                return [{"passed": False}] * len(task_ids)
            elif not is_candidate and not is_held_out:
                # Baseline on held-in: worse
                return [{"passed": False}] * len(task_ids)
            else:
                # Baseline on held-out: passes
                return [{"passed": True}] * len(task_ids)

        gate = RegressionGate(task_runner=_runner)
        decision = await gate.validate(
            baseline=baseline,
            candidate=candidate,
            held_in_tasks=["hi1", "hi2"],
            held_out_tasks=["ho1", "ho2"],
            repeats=1,
        )
        assert not decision.accepted
        assert decision.delta_in > 0   # Improved on held-in
        assert decision.delta_ho < 0   # Regressed on held-out

    @pytest.mark.asyncio
    async def test_no_improvement_rejects(self):
        """If Δ_in = 0 and Δ_ho = 0, gate rejects (no change)."""
        from weebot.application.services.regression_gate import RegressionGate

        gate = RegressionGate(task_runner=_task_runner_all_pass)
        decision = await gate.validate(
            baseline=_make_config(),
            candidate=_make_config(),
            held_in_tasks=["a", "b"],
            held_out_tasks=["c"],
            repeats=1,
        )
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

    @pytest.mark.asyncio
    async def test_empty_tasks_no_crash(self):
        """Empty task lists should not crash — short-circuit to (0, 0)."""
        from weebot.application.services.regression_gate import RegressionGate

        gate = RegressionGate(task_runner=_task_runner_all_pass)
        decision = await gate.validate(
            baseline=_make_config(),
            candidate=_make_config(),
            held_in_tasks=[],
            held_out_tasks=[],
            repeats=1,
        )
        assert not decision.accepted  # Δ_in=0, Δ_ho=0 → no improvement

    @pytest.mark.asyncio
    async def test_repeats_aggregate(self):
        """Multiple repeats should aggregate pass rates."""
        from weebot.application.services.regression_gate import RegressionGate

        call_count = {"n": 0}

        async def _runner(task_ids, config):
            call_count["n"] += 1
            if config.description == "better":
                return [{"passed": True}] * len(task_ids)
            return [{"passed": False}] * len(task_ids)

        gate = RegressionGate(task_runner=_runner)
        decision = await gate.validate(
            baseline=_make_config(),
            candidate=_make_config(description="better"),
            held_in_tasks=["t1"],
            held_out_tasks=["t2"],
            repeats=3,
        )
        assert decision.accepted
        # 2 splits × 2 configs × 3 repeats = 12 calls
        assert call_count["n"] == 12


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
