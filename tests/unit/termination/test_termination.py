"""Unit tests for composable termination conditions (Improvement #2)."""
import pytest

from weebot.application.termination.base import (
    CompositeTermination,
    TerminationContext,
    TerminationResult,
)
from weebot.application.termination.conditions import (
    MaxIterationTermination,
    TokenBudgetTermination,
    WallClockTermination,
    TextMentionTermination,
)


class TestMaxIterationTermination:
    def test_continues_below_limit(self):
        cond = MaxIterationTermination(max_iterations=10)
        result = cond.check(TerminationContext(iteration=5))
        assert not result.should_terminate

    def test_terminates_at_limit(self):
        cond = MaxIterationTermination(max_iterations=10)
        result = cond.check(TerminationContext(iteration=10))
        assert result.should_terminate
        assert "10" in result.reason

    def test_terminates_above_limit(self):
        cond = MaxIterationTermination(max_iterations=10)
        result = cond.check(TerminationContext(iteration=15))
        assert result.should_terminate

    def test_rejects_invalid_max(self):
        with pytest.raises(ValueError, match="max_iterations"):
            MaxIterationTermination(max_iterations=0)


class TestTokenBudgetTermination:
    def test_continues_under_budget(self):
        cond = TokenBudgetTermination(max_tokens=100_000)
        result = cond.check(TerminationContext(total_tokens=50_000))
        assert not result.should_terminate

    def test_terminates_at_budget(self):
        cond = TokenBudgetTermination(max_tokens=100_000)
        result = cond.check(TerminationContext(total_tokens=100_000))
        assert result.should_terminate
        assert "100,000" in result.reason

    def test_terminates_over_budget(self):
        cond = TokenBudgetTermination(max_tokens=50000)
        result = cond.check(TerminationContext(total_tokens=60000))
        assert result.should_terminate

    def test_rejects_invalid_max(self):
        with pytest.raises(ValueError, match="max_tokens"):
            TokenBudgetTermination(max_tokens=0)


class TestWallClockTermination:
    def test_continues_under_timeout(self):
        cond = WallClockTermination(max_seconds=300.0)
        result = cond.check(TerminationContext(elapsed_seconds=150.0))
        assert not result.should_terminate

    def test_terminates_at_timeout(self):
        cond = WallClockTermination(max_seconds=60.0)
        result = cond.check(TerminationContext(elapsed_seconds=60.0))
        assert result.should_terminate

    def test_terminates_over_timeout(self):
        cond = WallClockTermination(max_seconds=60.0)
        result = cond.check(TerminationContext(elapsed_seconds=90.0))
        assert result.should_terminate

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            WallClockTermination(max_seconds=0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            WallClockTermination(max_seconds=-1.0)


class TestTextMentionTermination:
    def test_detects_keyword(self):
        cond = TextMentionTermination("FAILED", scan_last_n=5)
        ctx = TerminationContext(last_messages=[
            {"role": "assistant", "content": "everything is fine"},
            {"role": "tool", "content": "FAILED: connection refused"},
        ])
        result = cond.check(ctx)
        assert result.should_terminate
        assert "failed" in result.reason.lower()

    def test_ignores_when_not_present(self):
        cond = TextMentionTermination("FAILED", scan_last_n=5)
        ctx = TerminationContext(last_messages=[
            {"role": "assistant", "content": "everything is fine"},
        ])
        result = cond.check(ctx)
        assert not result.should_terminate

    def test_case_insensitive(self):
        cond = TextMentionTermination("done", scan_last_n=3)
        ctx = TerminationContext(last_messages=[
            {"role": "assistant", "content": "Task DONE successfully"},
        ])
        result = cond.check(ctx)
        assert result.should_terminate

    def test_empty_messages_safe(self):
        cond = TextMentionTermination("FAILED")
        ctx = TerminationContext(last_messages=[])
        result = cond.check(ctx)
        assert not result.should_terminate

    def test_no_last_messages_safe(self):
        cond = TextMentionTermination("FAILED")
        ctx = TerminationContext(last_messages=None)
        result = cond.check(ctx)
        assert not result.should_terminate

    def test_rejects_invalid_scan_n(self):
        with pytest.raises(ValueError, match="scan_last_n"):
            TextMentionTermination("text", scan_last_n=0)


class TestCompositeTermination:
    def test_or_mode_terminates_on_any(self):
        cond = MaxIterationTermination(5) | TokenBudgetTermination(10000)
        # Only iteration triggers
        result = cond.check(TerminationContext(iteration=6, total_tokens=100))
        assert result.should_terminate
        assert "max iterations" in result.reason

    def test_or_mode_continues_if_none_trigger(self):
        cond = MaxIterationTermination(10) | TokenBudgetTermination(10000)
        result = cond.check(TerminationContext(iteration=5, total_tokens=500))
        assert not result.should_terminate

    def test_and_mode_terminates_when_all_trigger(self):
        cond = MaxIterationTermination(5) & TokenBudgetTermination(5000)
        result = cond.check(TerminationContext(iteration=6, total_tokens=6000))
        assert result.should_terminate

    def test_and_mode_continues_if_only_one_triggers(self):
        cond = MaxIterationTermination(5) & TokenBudgetTermination(10000)
        result = cond.check(TerminationContext(iteration=6, total_tokens=500))
        assert not result.should_terminate

    def test_operator_or_syntax(self):
        cond = MaxIterationTermination(3) | WallClockTermination(3600.0)
        assert isinstance(cond, CompositeTermination)
        result = cond.check(TerminationContext(iteration=4))
        assert result.should_terminate

    def test_operator_and_syntax(self):
        cond = MaxIterationTermination(3) & TokenBudgetTermination(5000)
        assert isinstance(cond, CompositeTermination)
        result = cond.check(TerminationContext(iteration=4, total_tokens=100))
        assert not result.should_terminate

    def test_composite_rejects_invalid_mode(self):
        with pytest.raises(ValueError, match="mode"):
            CompositeTermination([], mode="xor")

    def test_empty_composite_never_terminates(self):
        cond = CompositeTermination([])
        result = cond.check(TerminationContext(iteration=1000))
        assert not result.should_terminate


class TestTerminationContext:
    def test_defaults(self):
        ctx = TerminationContext()
        assert ctx.iteration == 0
        assert ctx.total_tokens == 0
        assert ctx.elapsed_seconds == 0.0
        assert ctx.last_messages is None


class TestTerminationResult:
    def test_bool_coercion(self):
        assert bool(TerminationResult(True, "yes")) is True
        assert bool(TerminationResult(False, "no")) is False
