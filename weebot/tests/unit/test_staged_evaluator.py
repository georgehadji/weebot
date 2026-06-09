"""Tests for StagedEvaluator — probe-then-full evaluation."""
from __future__ import annotations

import pytest
from weebot.application.services.staged_evaluator import StagedEvaluator, StagedResult


class TestStagedEvaluator:
    """Tests for the two-phase evaluation protocol."""

    @pytest.fixture
    def tasks(self) -> list[str]:
        return [f"task-{i}" for i in range(50)]

    @pytest.fixture
    def evaluator(self) -> StagedEvaluator:
        return StagedEvaluator(probe_size=10, threshold=0.3)

    @pytest.mark.asyncio
    async def test_high_performer_gets_full_eval(
        self, evaluator: StagedEvaluator, tasks: list[str]
    ) -> None:
        async def eval_fn(agent, task_subset) -> float:
            return 0.8  # High performer

        result = await evaluator.evaluate(None, tasks, eval_fn)

        assert result.remaining_assumed_zero is False
        assert result.tasks_evaluated == 50
        assert result.tasks_skipped == 0
        assert result.probe_score == 0.8
        assert result.full_score == 0.8

    @pytest.mark.asyncio
    async def test_low_performer_skips_full_eval(
        self, evaluator: StagedEvaluator, tasks: list[str]
    ) -> None:
        call_count = 0

        async def eval_fn(agent, task_subset) -> float:
            nonlocal call_count
            call_count += 1
            return 0.1  # Low performer

        result = await evaluator.evaluate(None, tasks, eval_fn)

        assert result.remaining_assumed_zero is True
        assert result.tasks_evaluated == 10  # Only probe
        assert result.tasks_skipped == 40
        assert result.full_score is None
        assert call_count == 1  # Only one evaluation call (probe only)

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_gets_full_eval(
        self, evaluator: StagedEvaluator, tasks: list[str]
    ) -> None:
        async def eval_fn(agent, task_subset) -> float:
            return 0.3  # Exactly at threshold

        result = await evaluator.evaluate(None, tasks, eval_fn)

        # threshold 0.3, score 0.3 → >= threshold → full eval
        assert result.remaining_assumed_zero is False
        assert result.tasks_evaluated == 50

    @pytest.mark.asyncio
    async def test_small_task_set_no_staging(
        self, tasks: list[str]
    ) -> None:
        evaluator = StagedEvaluator(probe_size=10, threshold=0.3)
        small_tasks = tasks[:5]  # Fewer than probe_size

        async def eval_fn(agent, task_subset) -> float:
            return 0.5

        result = await evaluator.evaluate(None, small_tasks, eval_fn)

        assert result.tasks_evaluated == 5
        assert result.tasks_skipped == 0
        assert result.remaining_assumed_zero is False

    def test_invalid_probe_size_raises(self) -> None:
        with pytest.raises(ValueError, match="probe_size"):
            StagedEvaluator(probe_size=0)

    def test_invalid_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            StagedEvaluator(threshold=1.5)

        with pytest.raises(ValueError, match="threshold"):
            StagedEvaluator(threshold=-0.1)
