"""Unit tests for ModelCascadeTracker — enriched CascadeDecision fields + per-category stats."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from weebot.core.model_cascade_tracker import (
    CascadeDecision,
    CascadeOutcome,
    CascadeTier,
    ModelCascadeTracker,
)


class TestCascadeDecisionFields:
    """New ACR fields must default safely for backward compatibility."""

    def test_minimal_construction(self):
        """A CascadeDecision with only the original fields still works."""
        d = CascadeDecision(
            model_name="test-model",
            tier=CascadeTier.FREE,
            outcome=CascadeOutcome.SUCCESS,
            latency_ms=100.0,
        )
        assert d.model_name == "test-model"
        assert d.tier == CascadeTier.FREE
        assert d.outcome == CascadeOutcome.SUCCESS
        assert d.latency_ms == 100.0

    def test_new_fields_default_to_general_and_none(self):
        """New fields have safe defaults."""
        d = CascadeDecision(
            model_name="test-model",
            tier=CascadeTier.BUDGET,
            outcome=CascadeOutcome.FAILED,
            latency_ms=50.0,
        )
        assert d.task_category == "general"
        assert d.json_valid is None
        assert d.tool_success is None
        assert d.retries == 0
        assert d.critic_score is None

    def test_new_fields_can_be_set(self):
        """New fields accept explicit values."""
        d = CascadeDecision(
            model_name="test-model",
            tier=CascadeTier.PREMIUM,
            outcome=CascadeOutcome.SUCCESS,
            latency_ms=200.0,
            task_category="coding",
            json_valid=True,
            tool_success=True,
            retries=2,
            critic_score=0.85,
        )
        assert d.task_category == "coding"
        assert d.json_valid is True
        assert d.tool_success is True
        assert d.retries == 2
        assert d.critic_score == 0.85

    def test_immutable(self):
        """CascadeDecision remains frozen."""
        d = CascadeDecision(
            model_name="m", tier=CascadeTier.FREE, outcome=CascadeOutcome.SUCCESS, latency_ms=0.0,
        )
        with pytest.raises(AttributeError):
            d.model_name = "other"  # type: ignore[misc]

    def test_timestamp_defaults_to_now(self):
        """Timestamp defaults to current UTC time."""
        before = datetime.now(timezone.utc)
        d = CascadeDecision(
            model_name="m", tier=CascadeTier.FREE, outcome=CascadeOutcome.SUCCESS, latency_ms=0.0,
        )
        after = datetime.now(timezone.utc)
        assert before <= d.timestamp <= after


class TestPerCategoryStats:
    """per_category_stats() must correctly aggregate by category and model."""

    def test_empty_tracker_returns_empty(self):
        tracker = ModelCascadeTracker(max_decisions=100)
        stats = tracker.per_category_stats()
        assert stats == {}

    def test_single_category_single_model(self):
        tracker = ModelCascadeTracker(max_decisions=100)
        tracker.record(CascadeDecision(
            model_name="model-a",
            tier=CascadeTier.FREE,
            outcome=CascadeOutcome.SUCCESS,
            latency_ms=100.0,
            cost_estimate=0.001,
            task_category="coding",
        ))
        stats = tracker.per_category_stats()
        assert "coding" in stats
        assert "model-a" in stats["coding"]
        m = stats["coding"]["model-a"]
        assert m["attempts"] == 1
        assert m["successes"] == 1
        assert m["failures"] == 0
        assert m["success_rate"] == 1.0
        assert m["mean_latency_ms"] == 100.0
        assert m["mean_cost"] == 0.001

    def test_multi_category_multi_model(self):
        tracker = ModelCascadeTracker(max_decisions=100)
        # coding / model-a: 2 success, 1 fail
        for _ in range(2):
            tracker.record(CascadeDecision(
                model_name="model-a", tier=CascadeTier.FREE,
                outcome=CascadeOutcome.SUCCESS, latency_ms=50.0,
                task_category="coding",
            ))
        tracker.record(CascadeDecision(
            model_name="model-a", tier=CascadeTier.BUDGET,
            outcome=CascadeOutcome.FAILED, latency_ms=30.0,
            error_message="timeout", task_category="coding",
        ))
        # research / model-b: 1 success
        tracker.record(CascadeDecision(
            model_name="model-b", tier=CascadeTier.FREE,
            outcome=CascadeOutcome.SUCCESS, latency_ms=200.0,
            task_category="research",
        ))

        stats = tracker.per_category_stats()

        # Coding stats
        cod = stats["coding"]["model-a"]
        assert cod["attempts"] == 3
        assert cod["successes"] == 2
        assert cod["failures"] == 1
        assert cod["success_rate"] == pytest.approx(2 / 3, rel=1e-4)
        assert cod["mean_latency_ms"] == round((50 * 2 + 30) / 3, 1)

        # Research stats
        res = stats["research"]["model-b"]
        assert res["attempts"] == 1
        assert res["successes"] == 1
        assert res["success_rate"] == 1.0

    def test_clear_resets_per_category_stats(self):
        tracker = ModelCascadeTracker(max_decisions=100)
        tracker.record(CascadeDecision(
            model_name="model-a", tier=CascadeTier.FREE,
            outcome=CascadeOutcome.SUCCESS, latency_ms=10.0,
            task_category="coding",
        ))
        assert tracker.per_category_stats()
        tracker.clear()
        assert tracker.per_category_stats() == {}


class TestRouterDedup:
    """task_model_router._PATTERNS must not have duplicate TaskCategory keys."""

    def test_no_duplicate_pattern_keys(self):
        from weebot.application.services.task_model_router import _PATTERNS
        from weebot.application.services.task_model_router import TaskCategory
        seen = set()
        for cat in _PATTERNS:
            assert cat not in seen, f"Duplicate TaskCategory key: {cat}"
            seen.add(cat)
        # Also verify every TaskCategory (except GENERAL) has at least one pattern
        for cat in TaskCategory:
            if cat.value == "general":
                continue
            assert cat in _PATTERNS, f"Missing patterns for TaskCategory.{cat.name}"
