"""Unit tests for with-vs-without A/B Evaluation (Harness Enhancement H6).

Covers:
- ComparisonResult computes correct delta and improvement string
- ComparisonReport aggregates results correctly
- ComparisonRunner._score_output heuristic
"""
import pytest


class TestComparisonResult:
    """Validates ComparisonResult dataclass."""

    def test_delta_positive(self):
        from weebot.application.harness.comparison_runner import ComparisonResult

        r = ComparisonResult(
            score_with=0.8, score_without=0.4, delta=0.4, passed=True,
        )
        assert r.delta == 0.4
        assert r.passed is True
        assert r.improvement == "significant"

    def test_delta_negative(self):
        from weebot.application.harness.comparison_runner import ComparisonResult

        r = ComparisonResult(
            score_with=0.3, score_without=0.7, delta=-0.4, passed=False,
        )
        assert r.delta == -0.4
        assert r.passed is False
        assert r.improvement == "regression"

    def test_delta_neutral(self):
        from weebot.application.harness.comparison_runner import ComparisonResult

        r = ComparisonResult(
            score_with=0.5, score_without=0.5, delta=0.0, passed=True,
        )
        assert r.improvement == "neutral"

    def test_delta_moderate(self):
        from weebot.application.harness.comparison_runner import ComparisonResult

        r = ComparisonResult(
            score_with=0.7, score_without=0.63, delta=0.07, passed=True,
        )
        assert r.improvement == "moderate"

    def test_delta_slight(self):
        from weebot.application.harness.comparison_runner import ComparisonResult

        r = ComparisonResult(
            score_with=0.7, score_without=0.68, delta=0.02, passed=True,
        )
        assert r.improvement == "slight"


class TestComparisonReport:
    """Validates ComparisonReport aggregation."""

    def test_empty_report(self):
        from weebot.application.harness.comparison_runner import ComparisonReport

        report = ComparisonReport(skill_name="test")
        assert report.avg_delta == 0.0
        assert report.avg_score_with == 0.0
        assert report.avg_score_without == 0.0
        assert report.pass_count == 0

    def test_aggregates_results(self):
        from weebot.application.harness.comparison_runner import (
            ComparisonReport,
            ComparisonResult,
        )

        report = ComparisonReport(skill_name="test")
        report.results = [
            ComparisonResult(score_with=0.8, score_without=0.4, delta=0.4, passed=True),
            ComparisonResult(score_with=0.6, score_without=0.5, delta=0.1, passed=True),
            ComparisonResult(score_with=0.3, score_without=0.7, delta=-0.4, passed=False),
        ]

        assert report.pass_count == 2
        assert report.total == 3
        assert report.avg_delta == pytest.approx(0.033, abs=0.01)
        assert report.avg_score_with == pytest.approx(0.567, abs=0.01)
        assert report.avg_score_without == pytest.approx(0.533, abs=0.01)


class TestComparisonRunner:
    """Validates ComparisonRunner scoring heuristics."""

    @pytest.mark.asyncio
    async def test_score_output_with_expected(self):
        """When expected is provided, score is based on token overlap."""
        from weebot.application.harness.comparison_runner import ComparisonRunner

        runner = ComparisonRunner(flow_factory=lambda **kw: None)
        score = await runner._score_output(
            "The quick brown fox", "the quick brown fox jumps",
        )
        assert 0.0 < score <= 1.0

    @pytest.mark.asyncio
    async def test_score_output_empty(self):
        """Empty output scores 0.0."""
        from weebot.application.harness.comparison_runner import ComparisonRunner

        runner = ComparisonRunner(flow_factory=lambda **kw: None)
        score = await runner._score_output("", None)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_output_non_empty(self):
        """Non-empty output without expected scores > 0."""
        from weebot.application.harness.comparison_runner import ComparisonRunner

        runner = ComparisonRunner(flow_factory=lambda **kw: None)
        score = await runner._score_output("Some output text here", None)
        assert score > 0.0
        assert score <= 1.0
