"""Tests verifying fixes for critical ai_router.py bugs.

Bug #1: Bare except swallowed asyncio.CancelledError (BaseException)
Bug #2: CostTracker.is_budget_exceeded() was defined but never called
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from weebot.ai_router import (
    CostTracker,
    ModelRouter,
    ResponseCache,
    TaskType,
)


# ---------------------------------------------------------------------------
# Bug #1: Cancellation propagates through fallback loop
# ---------------------------------------------------------------------------

class TestCancellationPropagation:
    """generate_with_fallback must NOT swallow asyncio.CancelledError."""

    @pytest.mark.asyncio
    async def test_cancellation_propagates_not_swallowed(self, tmp_path):
        """CancelledError raised inside _call_model must propagate out of generate_with_fallback."""
        router = ModelRouter(daily_budget=100.0, cache_dir=str(tmp_path))

        async def raise_cancelled(*args, **kwargs):
            raise asyncio.CancelledError("task cancelled")

        with patch.object(router, "_call_model", side_effect=raise_cancelled):
            with patch.object(router, "select_model", return_value="deepseek-chat"):
                # CancelledError must propagate — NOT be caught and converted to
                # "All models failed" exception
                with pytest.raises(asyncio.CancelledError):
                    await router.generate_with_fallback(
                        prompt="hello",
                        task_type=TaskType.CHAT,
                        use_cache=False,
                    )

    @pytest.mark.asyncio
    async def test_timeout_enforced_via_wait_for(self, tmp_path):
        """asyncio.wait_for timeout must be honoured — it uses CancelledError internally."""
        router = ModelRouter(daily_budget=100.0, cache_dir=str(tmp_path))

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)  # deliberate hang

        with patch.object(router, "_call_model", side_effect=slow_call):
            with patch.object(router, "select_model", return_value="deepseek-chat"):
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        router.generate_with_fallback(
                            prompt="slow",
                            task_type=TaskType.CHAT,
                            use_cache=False,
                        ),
                        timeout=0.05,
                    )

    @pytest.mark.asyncio
    async def test_regular_exception_still_falls_back(self, tmp_path):
        """Ordinary exceptions (not BaseException subclasses) still trigger fallback."""
        router = ModelRouter(daily_budget=100.0, cache_dir=str(tmp_path))

        call_count = 0

        async def primary_then_fallback(model_id: str, prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("primary model unavailable")
            return "fallback response"

        with patch.object(router, "_call_model", side_effect=primary_then_fallback):
            with patch.object(router, "select_model", return_value="deepseek-chat"):
                result = await router.generate_with_fallback(
                    prompt="test",
                    task_type=TaskType.CHAT,
                    use_cache=False,
                )
        assert result["content"] == "fallback response"
        assert call_count == 2  # primary + 1 fallback


# ---------------------------------------------------------------------------
# Bug #2: Budget enforcement
# ---------------------------------------------------------------------------

class TestBudgetEnforcement:
    """generate_with_fallback must raise BudgetExceededError when budget is exceeded."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_blocks_api_call(self, tmp_path):
        """No API call should be made when the daily budget has been exceeded."""
        from weebot.domain.exceptions import BudgetExceededError

        router = ModelRouter(daily_budget=0.001, cache_dir=str(tmp_path))
        # Manually set today_cost above the budget
        router.cost_tracker.today_cost = 1.0  # way over $0.001

        api_mock = AsyncMock(return_value="should not be called")
        with patch.object(router, "_call_model", api_mock):
            with pytest.raises(BudgetExceededError) as exc_info:
                await router.generate_with_fallback(
                    prompt="test",
                    task_type=TaskType.CHAT,
                    use_cache=False,
                )

        # Crucially: the API was NEVER called
        api_mock.assert_not_awaited()
        assert "budget" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_budget_not_exceeded_allows_api_call(self, tmp_path):
        """When budget is not exceeded, the API call proceeds normally."""
        router = ModelRouter(daily_budget=10.0, cache_dir=str(tmp_path))
        router.cost_tracker.today_cost = 0.0  # fresh budget

        with patch.object(router, "_call_model", AsyncMock(return_value="ok")):
            with patch.object(router, "select_model", return_value="deepseek-chat"):
                result = await router.generate_with_fallback(
                    prompt="hello",
                    task_type=TaskType.CHAT,
                    use_cache=False,
                )
        assert result["content"] == "ok"

    @pytest.mark.asyncio
    async def test_cache_hit_bypasses_budget_check(self, tmp_path):
        """A cached response should be returned without checking budget."""
        router = ModelRouter(daily_budget=0.001, cache_dir=str(tmp_path))
        router.cost_tracker.today_cost = 999.0  # massively over budget

        # Prime the cache manually
        cache_key = router._generate_cache_key("cached prompt", TaskType.CHAT)
        router.response_cache.set(cache_key, "cached result")

        # Should NOT raise BudgetExceededError — cache hit bypasses API
        result = await router.generate_with_fallback(
            prompt="cached prompt",
            task_type=TaskType.CHAT,
            use_cache=True,
        )
        assert result["content"] == "cached result"
        assert result["source"] == "cache"

    def test_cost_tracker_is_budget_exceeded_logic(self):
        """CostTracker.is_budget_exceeded() correctly reflects budget state."""
        tracker = CostTracker(daily_budget=5.0)
        assert tracker.is_budget_exceeded() is False

        tracker.today_cost = 4.99
        assert tracker.is_budget_exceeded() is False

        tracker.today_cost = 5.0
        assert tracker.is_budget_exceeded() is True

        tracker.today_cost = 5.01
        assert tracker.is_budget_exceeded() is True

    def test_cost_tracker_zero_budget(self):
        """A zero budget means every call is over budget immediately."""
        tracker = CostTracker(daily_budget=0.0)
        tracker.today_cost = 0.0
        assert tracker.is_budget_exceeded() is True
