"""Tests for PlanNoveltyTracker — diversity-driven re-planning."""
from __future__ import annotations

import pytest
from weebot.application.services.plan_novelty import PlanNoveltyTracker
from weebot.domain.models.plan import Plan, Step


def _make_plan(title: str, descriptions: list[str]) -> Plan:
    return Plan(
        title=title,
        message="",
        steps=[
            Step(id=f"step-{i+1}", description=desc, status="pending")
            for i, desc in enumerate(descriptions)
        ],
    )


class TestDiversityScore:
    """Tests for plan diversity measurement."""

    def test_single_plan_is_maximally_diverse(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [_make_plan("P1", ["Do A", "Do B"])]
        assert tracker.diversity_score(plans) == 1.0

    def test_identical_plans_have_zero_diversity(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A", "Do B"]),
            _make_plan("P2", ["Do A", "Do B"]),
        ]
        score = tracker.diversity_score(plans)
        assert score == 0.5  # 2 unique out of 4 total

    def test_completely_different_plans_have_full_diversity(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A", "Do B"]),
            _make_plan("P2", ["Do C", "Do D"]),
        ]
        assert tracker.diversity_score(plans) == 1.0

    def test_partial_overlap(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A", "Do B"]),
            _make_plan("P2", ["Do A", "Do C"]),
        ]
        score = tracker.diversity_score(plans)
        # 3 unique descriptions (A, B, C) out of 4 total
        assert score == 0.75

    def test_empty_plans_return_one(self) -> None:
        tracker = PlanNoveltyTracker()
        assert tracker.diversity_score([]) == 1.0


class TestFrequentApproaches:
    """Tests for frequent step detection."""

    def test_no_frequent_with_few_plans(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A"]),
            _make_plan("P2", ["Do A"]),
        ]
        approaches = tracker.frequent_approaches(plans)
        assert approaches == []  # 2 < 3 threshold

    def test_frequent_after_three_occurrences(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A"]),
            _make_plan("P2", ["Do A"]),
            _make_plan("P3", ["Do A"]),
        ]
        approaches = tracker.frequent_approaches(plans)
        assert "do a" in approaches

    def test_custom_min_count(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A"]),
            _make_plan("P2", ["Do A"]),
        ]
        approaches = tracker.frequent_approaches(plans, min_count=2)
        assert "do a" in approaches

    def test_ordered_by_frequency(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A"]),
            _make_plan("P2", ["Do A"]),
            _make_plan("P3", ["Do A"]),
            _make_plan("P4", ["Do B"]),
            _make_plan("P5", ["Do B"]),
            _make_plan("P6", ["Do B"]),
            _make_plan("P7", ["Do C"]),
            _make_plan("P8", ["Do C"]),
            _make_plan("P9", ["Do C"]),
        ]
        approaches = tracker.frequent_approaches(plans)
        # All have 3 occurrences, but "do a" should come first (most_common tie)
        assert len(approaches) == 3


class TestAvoidancePrompt:
    """Tests for avoidance prompt generation."""

    def test_empty_when_no_frequent_approaches(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [_make_plan("P1", ["Do A"])]
        prompt = tracker.avoidance_prompt(plans)
        assert prompt == ""

    def test_generates_avoidance_list(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = [
            _make_plan("P1", ["Do A"]),
            _make_plan("P2", ["Do A"]),
            _make_plan("P3", ["Do A"]),
        ]
        prompt = tracker.avoidance_prompt(plans)
        assert "AVOID" in prompt
        assert "do a" in prompt.lower()
        assert "fundamentally DIFFERENT" in prompt

    def test_caps_at_five_approaches(self) -> None:
        tracker = PlanNoveltyTracker()
        plans = []
        for i in range(6):
            for _ in range(3):
                plans.append(_make_plan(f"P{i}", [f"Do Task {i}"]))
        prompt = tracker.avoidance_prompt(plans)
        # Should have at most 5 "- " lines for approaches
        approach_lines = [
            line for line in prompt.split("\n") if line.startswith("- ")
        ]
        assert len(approach_lines) <= 5
