"""Unit tests for ACR Phase P3 — benchmark suites and runner."""

from __future__ import annotations

import pytest

from weebot.domain.models.capability import CapabilityAxis
from weebot.infrastructure.benchmark.suites import (
    ALL_SUITES,
    SUITES_BY_AXIS,
    BenchmarkItem,
    BenchmarkSuite,
)
from weebot.infrastructure.benchmark.runner import BenchmarkRunner, CostGuardError


class TestBenchmarkSuites:
    """Suites must be well-formed and score deterministically."""

    def test_all_suites_have_items(self):
        for suite in ALL_SUITES:
            assert len(suite.items) >= 1, f"{suite.name} has no items"
            assert suite.axis in (
                "reasoning",
                "coding",
                "writing",
                "math",
                "long_context",
                "tool_use",
            )
        assert len(ALL_SUITES) == 6

    def test_suites_by_axis_complete(self):
        for axis in ("reasoning", "coding", "writing", "math", "long_context", "tool_use"):
            assert axis in SUITES_BY_AXIS

    def test_perfect_score(self):
        item = BenchmarkItem("test", expected=["hello", "world"])
        assert item.score_response("hello world") == 10.0
        assert item.score_response("Hello WORLD") == 10.0  # case-insensitive

    def test_partial_score_is_zero(self):
        """Missing any keyword → 0 (strict rubric)."""
        item = BenchmarkItem("test", expected=["hello", "world"])
        assert item.score_response("hello") == 0.0
        assert item.score_response("") == 0.0

    def test_suite_scoring(self):
        suite = BenchmarkSuite(
            "test",
            "reasoning",
            [BenchmarkItem("q1", expected=["a"]), BenchmarkItem("q2", expected=["b"])],
        )
        score = suite.score_all(["answer a", "answer b"])
        assert score == 10.0

    def test_suite_scoring_partial(self):
        suite = BenchmarkSuite(
            "test",
            "reasoning",
            [BenchmarkItem("q1", expected=["a"]), BenchmarkItem("q2", expected=["b"])],
        )
        score = suite.score_all(["answer a", "wrong"])
        assert score == 5.0  # half credit

    def test_empty_suite(self):
        suite = BenchmarkSuite("empty", "reasoning", [])
        assert suite.score_all([]) == 0.0


class TestBenchmarkRunner:
    """Runner must score deterministically with a mock LLM."""

    @staticmethod
    def _mock_llm(model_id: str, messages: list) -> str:
        """Return a response that matches all expected keywords for any prompt."""
        return "The answer contains all expected keywords 4 reverse head prev 555 $0.05"

    @staticmethod
    def _mock_llm_failing(model_id: str, messages: list) -> str:
        """Return a response that matches nothing."""
        return "I don't know."

    @staticmethod
    def _mock_llm_error(model_id: str, messages: list) -> str:
        raise RuntimeError("API error")

    async def test_mock_model_gets_score(self):
        runner = BenchmarkRunner(call_llm=self._mock_llm, cost_ceiling=10.0)
        profile = await runner.run("test-model", suites=[ALL_SUITES[0]])
        assert profile is not None
        assert profile.source == "benchmark"
        assert profile.model_id == "test-model"
        for axis, score in profile.axes.items():
            assert 0.0 <= score <= 10.0
            assert isinstance(axis, CapabilityAxis)
        print(f"Profile axes: {[(a.value, s) for a, s in profile.axes.items()]}")

    async def test_poor_model_gets_low_score(self):
        runner = BenchmarkRunner(call_llm=self._mock_llm_failing, cost_ceiling=10.0)
        profile = await runner.run("bad-model", suites=[ALL_SUITES[0]])
        assert profile is not None
        for score in profile.axes.values():
            assert score == 0.0, f"Expected 0, got {score}"

    async def test_runner_returns_profile_with_zero_on_all_failures(self):
        runner = BenchmarkRunner(call_llm=self._mock_llm_error, cost_ceiling=10.0, max_retries=0)
        profile = await runner.run("error-model", suites=[ALL_SUITES[0]])
        # All items failed, but profile is still created with 0.0 scores
        assert profile is not None
        assert profile.source == "benchmark"
        for score in profile.axes.values():
            assert score == 0.0, f"Expected 0.0, got {score}"

    async def test_cost_guard_aborts(self):
        runner = BenchmarkRunner(call_llm=self._mock_llm, cost_ceiling=0.0)
        with pytest.raises(CostGuardError):
            await runner.run("deepseek-r1", suites=[ALL_SUITES[0]])

    async def test_cost_guard_allows_under_budget(self):
        runner = BenchmarkRunner(call_llm=self._mock_llm, cost_ceiling=10.0)
        profile = await runner.run("deepseek-r1", suites=[ALL_SUITES[0]])
        assert profile is not None

    async def test_get_total_items(self):
        runner = BenchmarkRunner(call_llm=self._mock_llm)
        assert runner.get_total_items(ALL_SUITES) == 15
        assert runner.get_total_items([ALL_SUITES[0]]) == 3
