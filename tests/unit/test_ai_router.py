"""Unit tests for ModelRouter, CostTracker, and ResponseCache."""
import pytest
from unittest.mock import patch
from weebot.ai_router import ModelRouter, CostTracker, ResponseCache, TaskType


class TestModelRouterSelection:
    def test_raises_when_no_api_keys_available(self, clean_env, tmp_cache):
        router = ModelRouter(cache_dir=str(tmp_cache))
        with pytest.raises(ValueError, match="No suitable model found"):
            router.select_model(TaskType.CHAT)

    def test_selects_model_when_key_available(self, monkeypatch, tmp_cache):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        router = ModelRouter(cache_dir=str(tmp_cache))
        model_id = router.select_model(TaskType.CHAT)
        assert model_id in ModelRouter.MODELS

    def test_prefers_model_with_matching_strengths(self, monkeypatch, tmp_cache):
        # gpt-4o-mini has CHAT in its strengths; if only openai key available it should win
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        router = ModelRouter(cache_dir=str(tmp_cache))
        model_id = router.select_model(TaskType.CHAT)
        assert model_id == "gpt-4o-mini"

    def test_budget_constraint_excludes_expensive_models(self, monkeypatch, tmp_cache):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("KIMI_API_KEY", "kimi-test")
        router = ModelRouter(cache_dir=str(tmp_cache))
        # kimi costs 0.015 per 1k; restrict to 0.001 to exclude it
        model_id = router.select_model(TaskType.CHAT, budget_constraint=0.001)
        assert model_id == "gpt-4o-mini"

    def test_returns_string_model_id(self, monkeypatch, tmp_cache):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        router = ModelRouter(cache_dir=str(tmp_cache))
        result = router.select_model(TaskType.DOCUMENTATION)
        assert isinstance(result, str)


class TestCostTracker:
    def test_initial_cost_is_zero(self):
        tracker = CostTracker(daily_budget=10.0)
        assert tracker.today_cost == 0.0

    def test_initial_call_count_is_zero(self):
        tracker = CostTracker(daily_budget=10.0)
        assert tracker.call_count == 0

    def test_budget_not_exceeded_initially(self):
        tracker = CostTracker(daily_budget=10.0)
        assert tracker.is_budget_exceeded() is False

    def test_budget_exceeded_when_cost_equals_budget(self):
        tracker = CostTracker(daily_budget=0.001)
        tracker.today_cost = 0.001
        assert tracker.is_budget_exceeded() is True

    def test_get_stats_returns_correct_structure(self):
        tracker = CostTracker(daily_budget=5.0)
        stats = tracker.get_stats()
        assert "today" in stats
        assert "budget" in stats
        assert "remaining" in stats
        assert "calls" in stats

    def test_remaining_budget_calculated_correctly(self):
        tracker = CostTracker(daily_budget=5.0)
        tracker.today_cost = 2.0
        stats = tracker.get_stats()
        assert stats["remaining"] == 3.0

    def test_record_call_increments_call_count(self):
        tracker = CostTracker(daily_budget=10.0)
        # gpt-4o-mini exists in MODELS so cost can be recorded
        tracker.record_call("gpt-4o-mini", input_tokens=100, output_tokens=50)
        assert tracker.call_count == 1

    def test_record_call_unknown_model_does_not_crash(self):
        tracker = CostTracker(daily_budget=10.0)
        tracker.record_call("nonexistent-model", input_tokens=100, output_tokens=50)
        assert tracker.call_count == 0  # No config found, nothing recorded


class TestResponseCache:
    def test_miss_returns_none(self, tmp_cache):
        cache = ResponseCache(tmp_cache)
        assert cache.get("missing-key") is None

    def test_set_then_get_returns_value(self, tmp_cache):
        cache = ResponseCache(tmp_cache)
        cache.set("my-key", "hello")
        assert cache.get("my-key") == "hello"

    def test_different_keys_stored_independently(self, tmp_cache):
        cache = ResponseCache(tmp_cache)
        cache.set("key-a", "value-a")
        cache.set("key-b", "value-b")
        assert cache.get("key-a") == "value-a"
        assert cache.get("key-b") == "value-b"

    def test_expired_entry_returns_none(self, tmp_cache):
        import time
        cache = ResponseCache(tmp_cache, ttl_hours=0)  # immediately expired
        cache.set("stale-key", "old data")
        # TTL is 0 hours — wait a moment and fetch
        time.sleep(0.01)
        assert cache.get("stale-key") is None
