"""Tests for Phase 1: Evidence-gated harness evolution.

Covers:
1. RegressionGate fail-closed default
2. RegressionGate composite-metric acceptance/rejection
3. HarnessMetricScorer from a known session
5. TaskRunReport with composite metrics
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.domain.models.harness_metrics import HarnessMetrics

# ============================================================================
# 1. RegressionGate — fail-closed default
# ============================================================================


class TestRegressionGateFailClosed:
    """RegressionGate must reject when no task_runner is configured."""

    @pytest.mark.asyncio
    async def test_rejects_without_runner_by_default(self):
        """No task_runner + no auto_accept => accepted is False."""
        from weebot.application.services.regression_gate import RegressionGate

        gate = RegressionGate()
        result = await gate.validate(baseline="v1", candidate="v2")
        assert not result.accepted
        assert "fail-closed" in result.reason

    @pytest.mark.asyncio
    async def test_accepts_with_auto_accept_flag(self):
        """auto_accept=True + no runner => accepted is True (legacy compat)."""
        from weebot.application.services.regression_gate import RegressionGate

        gate = RegressionGate(auto_accept=True)
        result = await gate.validate(baseline="v1", candidate="v2")
        assert result.accepted
        assert "auto_accept" in result.reason

    @pytest.mark.asyncio
    async def test_rejects_with_insufficient_held_out_tasks(self):
        """Fewer held-out tasks than min_held_out_tasks => reject."""
        from weebot.application.services.regression_gate import RegressionGate

        stub_runner = AsyncMock(
            return_value=[
                {"passed": True, "metrics": HarnessMetrics(task_pass_rate=1.0).model_dump()}
            ]
        )
        gate = RegressionGate(task_runner=stub_runner, min_held_out_tasks=2)

        result = await gate.validate(
            baseline="v1",
            candidate="v2",
            held_in_tasks=["a", "b"],
            held_out_tasks=["c"],  # only 1, below floor of 2
        )
        assert not result.accepted
        assert "Too few" in result.reason


# ============================================================================
# 2. RegressionGate — composite metric acceptance
# ============================================================================


class TestRegressionGateComposite:
    """RegressionGate uses composite metric for acceptance/rejection."""

    @staticmethod
    def _make_result(passed: bool, **overrides) -> dict:
        metrics = HarnessMetrics(task_pass_rate=1.0 if passed else 0.0, **overrides)
        return {"passed": passed, "metrics": metrics.model_dump()}

    @pytest.mark.asyncio
    async def test_accepts_when_both_splits_non_regressing(self):
        """Δ_composite_in ≥ 0 AND Δ_composite_ho ≥ 0 => accepted."""
        from weebot.application.services.regression_gate import RegressionGate

        # Baseline returns lower pass rate, candidate returns higher
        baseline_runner = AsyncMock(
            return_value=[self._make_result(True, trajectory_efficiency=0.5)]
        )
        candidate_runner = AsyncMock(
            return_value=[self._make_result(True, trajectory_efficiency=0.9)]
        )

        # Use separate gates for baseline vs candidate eval via side_effect
        calls = []

        async def side_effect(task_ids, config):
            calls.append(config)
            if len(calls) <= 1:  # baseline pass
                return [self._make_result(True, trajectory_efficiency=0.5)]
            return [self._make_result(True, trajectory_efficiency=0.9)]

        gate = RegressionGate(task_runner=side_effect)
        result = await gate.validate(
            baseline="v1",
            candidate="v2",
            held_in_tasks=["a", "b"],
            held_out_tasks=["c", "d"],
            repeats=1,
        )
        assert result.accepted, f"Expected ACCEPT, got: {result.reason}"

    @pytest.mark.asyncio
    async def test_rejects_when_held_out_regresses(self):
        """Δ_composite_ho < 0 => rejected."""
        from weebot.application.services.regression_gate import RegressionGate

        # Track the run order: baseline held-in → baseline held-out → candidate held-in → candidate held-out
        run_phase = [0]

        async def side_effect(task_ids, config):
            phase = run_phase[0]
            run_phase[0] += 1
            if phase < 2:  # baseline runs (held-in + held-out, good scores)
                return [
                    {
                        "passed": True,
                        "metrics": HarnessMetrics(
                            task_pass_rate=0.8, trajectory_efficiency=0.7
                        ).model_dump(),
                    }
                ]
            # candidate: held-in still good, but held-out regresses
            if phase == 2:  # candidate held-in (still good — pass delta)
                return [
                    {
                        "passed": True,
                        "metrics": HarnessMetrics(
                            task_pass_rate=0.9, trajectory_efficiency=0.8
                        ).model_dump(),
                    }
                ]
            # candidate held-out (regresses)
            return [
                {
                    "passed": True,
                    "metrics": HarnessMetrics(
                        task_pass_rate=0.3, trajectory_efficiency=0.2
                    ).model_dump(),
                }
            ]

        gate = RegressionGate(task_runner=side_effect, min_held_out_tasks=1)
        result = await gate.validate(
            baseline="v1", candidate="v2", held_in_tasks=["a"], held_out_tasks=["b"], repeats=1
        )
        assert not result.accepted
        assert "regression" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_when_no_improvement(self):
        """Δ_composite_in=0 AND Δ_composite_ho=0 => rejected."""
        from weebot.application.services.regression_gate import RegressionGate

        async def side_effect(task_ids, config):
            return [
                {"passed": True, "metrics": HarnessMetrics(task_pass_rate=0.5).model_dump()}
            ] * len(task_ids)

        gate = RegressionGate(task_runner=side_effect, min_held_out_tasks=1)
        result = await gate.validate(
            baseline="v1", candidate="v2", held_in_tasks=["a"], held_out_tasks=["b"], repeats=1
        )
        assert not result.accepted
        assert "No improvement" in result.reason


# ============================================================================
# 3. HarnessMetricScorer
# ============================================================================


class TestHarnessMetricScorer:
    """HarnessMetricScorer computes metrics from session events."""

    def test_score_passed_session_returns_high_scores(self):
        """A session that passed should have high task_pass_rate."""
        from weebot.application.services.harness_metric_scorer import HarnessMetricScorer

        session = MagicMock()
        session.events = []

        metrics = HarnessMetricScorer.score(session, task_passed=True)
        assert metrics.task_pass_rate == 1.0
        assert 0.0 <= metrics.composite() <= 1.0

    def test_score_failed_session_returns_low_pass_rate(self):
        """A session that failed should have zero task_pass_rate."""
        from weebot.application.services.harness_metric_scorer import HarnessMetricScorer

        session = MagicMock()
        session.events = []

        metrics = HarnessMetricScorer.score(session, task_passed=False)
        assert metrics.task_pass_rate == 0.0

    def test_recovery_ability_perfect_when_no_errors(self):
        """No errors => recovery_ability should be 1.0."""
        from weebot.application.services.harness_metric_scorer import HarnessMetricScorer

        session = MagicMock()
        session.events = []

        metrics = HarnessMetricScorer.score(session, task_passed=True)
        assert metrics.recovery_ability == 1.0

    def test_composite_default_weights_clamped(self):
        """Composite score with default weights stays in [0, 1]."""
        metrics = HarnessMetrics(
            trajectory_efficiency=0.9,
            verification_strength=0.9,
            recovery_ability=0.9,
            state_consistency=0.9,
            safety_compliance=0.9,
            replayability=0.9,
            task_pass_rate=0.9,
        )
        composite = metrics.composite()
        assert 0.0 <= composite <= 1.0
        assert composite > 0.8  # all high => composite high

    def test_composite_zero_for_all_zero_metrics(self):
        """All metrics zero => composite should be 0."""
        metrics = HarnessMetrics()
        assert metrics.composite() == 0.0


# ============================================================================
# 5. HarnessMetrics model
# ============================================================================


class TestHarnessMetricsModel:
    """HarnessMetrics domain model validation."""

    def test_defaults_are_zero(self):
        """All fields default to 0.0."""
        m = HarnessMetrics()
        assert m.trajectory_efficiency == 0.0
        assert m.verification_strength == 0.0
        assert m.recovery_ability == 0.0
        assert m.state_consistency == 0.0
        assert m.safety_compliance == 0.0
        assert m.replayability == 0.0
        assert m.task_pass_rate == 0.0

    def test_fields_validated_ge_le(self):
        """Fields raise ValidationError for out-of-range values."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HarnessMetrics(task_pass_rate=1.5)
        with pytest.raises(pydantic.ValidationError):
            HarnessMetrics(task_pass_rate=-0.1)

    def test_composite_raises_on_zero_weights(self):
        """Custom weights with sum=0 should raise ValueError."""
        m = HarnessMetrics(task_pass_rate=0.5)
        with pytest.raises(ValueError, match="Sum of weights"):
            m.composite(weights={"task_pass_rate": 0.0})

    def test_str_representation(self):
        """__str__ should include metric values."""
        m = HarnessMetrics(task_pass_rate=0.5)
        s = str(m)
        assert "pass=0.500" in s
