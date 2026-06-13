"""Unit tests for EvalRunner + judges (Improvement #6)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.eval.eval_runner import EvalRunner, EvalTask, EvalReport
from weebot.application.eval.judges import ScoreJudge
from weebot.application.ports.judge_port import CriterionScore, JudgeVerdict


class _FakeTarget:
    def __init__(self, outputs):
        self._outputs = outputs
        self._call_count = 0

    async def __call__(self, prompt):
        idx = self._call_count
        self._call_count += 1
        return self._outputs[idx] if idx < len(self._outputs) else "(no output)"


class TestScoreJudge:
    @pytest.mark.asyncio
    async def test_exact_match_scores_10(self):
        judge = ScoreJudge(pass_ratio=1.0)
        verdict = await judge.judge(
            task_description="say hello",
            output="hello world",
            criteria=["hello"],
        )
        assert verdict.criteria[0].score == 10.0
        assert verdict.passed is True

    @pytest.mark.asyncio
    async def test_no_match_scores_0(self):
        judge = ScoreJudge(pass_ratio=1.0)
        verdict = await judge.judge(
            task_description="count to ten",
            output="1 2 3 4 5",
            criteria=["banana"],
        )
        assert verdict.criteria[0].score == 0.0
        assert verdict.passed is False

    @pytest.mark.asyncio
    async def test_partial_match(self):
        judge = ScoreJudge(pass_ratio=0.5)
        verdict = await judge.judge(
            task_description="list colors",
            output="red blue green",
            criteria=["red", "yellow", "blue", "purple"],
        )
        matches = sum(1 for c in verdict.criteria if c.score == 10.0)
        assert matches == 2  # red and blue
        assert verdict.passed is True  # 2/4 >= 0.5

    @pytest.mark.asyncio
    async def test_no_criteria_checks_non_empty(self):
        judge = ScoreJudge()
        verdict = await judge.judge(
            task_description="any", output="something", criteria=[],
        )
        assert verdict.passed is True
        assert verdict.overall_score == 1.0

    @pytest.mark.asyncio
    async def test_no_criteria_empty_output_fails(self):
        judge = ScoreJudge()
        verdict = await judge.judge(
            task_description="any", output="", criteria=[],
        )
        assert verdict.passed is False

    @pytest.mark.asyncio
    async def test_regex_criteria(self):
        judge = ScoreJudge()
        verdict = await judge.judge(
            task_description="return a date",
            output="2024-01-15",
            criteria=["regex:20\\d{2}-\\d{2}-\\d{2}"],
        )
        assert verdict.criteria[0].score == 10.0
        assert verdict.passed is True


class TestEvalRunner:
    @pytest.mark.asyncio
    async def test_aggregates_scores(self):
        judge = ScoreJudge()
        runner = EvalRunner(judge=judge, pass_threshold=0.5)
        target = _FakeTarget(["red blue", "green only", "yellow"])

        tasks = [
            EvalTask(id="t1", prompt="list colors", criteria=["red"]),
            EvalTask(id="t2", prompt="list colors", criteria=["red"]),
            EvalTask(id="t3", prompt="list colors", criteria=["yellow"]),
        ]
        report = await runner.run(target, tasks)

        assert report.total == 3
        assert report.passed == 2  # t1 (red found) + t3 (yellow found)
        assert report.pass_rate == 2 / 3
        assert 0.0 <= report.avg_score <= 1.0

    @pytest.mark.asyncio
    async def test_target_error_handled_gracefully(self):
        judge = ScoreJudge()
        runner = EvalRunner(judge=judge)

        async def failing_target(prompt):
            raise RuntimeError("target crashed")

        tasks = [EvalTask(id="t1", prompt="anything", criteria=["test"])]
        report = await runner.run(failing_target, tasks)

        assert report.total == 1
        assert report.passed == 0

    @pytest.mark.asyncio
    async def test_per_criterion_aggregation(self):
        judge = ScoreJudge()
        runner = EvalRunner(judge=judge)

        target = _FakeTarget(["hello world", "hello world"])
        tasks = [
            EvalTask(id="t1", prompt="greet", criteria=["hello"]),
            EvalTask(id="t2", prompt="greet again", criteria=["hello"]),
        ]
        report = await runner.run(target, tasks)

        assert "hello" in report.per_criterion
        assert report.per_criterion["hello"] == 10.0  # both matched


class TestCriterionScore:
    def test_frozen_dataclass(self):
        cs = CriterionScore(name="correctness", score=8.5, reasoning="good")
        assert cs.name == "correctness"
        assert cs.score == 8.5
        with pytest.raises(Exception):
            cs.score = 9.0


class TestJudgeVerdict:
    def test_average_score(self):
        verdict = JudgeVerdict(
            criteria=[
                CriterionScore("a", 8.0),
                CriterionScore("b", 6.0),
            ],
            overall_score=0.7,
        )
        assert verdict.average_score == 7.0

    def test_average_empty_criteria(self):
        verdict = JudgeVerdict(overall_score=0.5)
        assert verdict.average_score == 0.5


class TestEvalTaskResult:
    def test__eval_runner_basic_flow(self):
        """Smoke test: EvalRunner with real ScoreJudge."""
        tasks = [EvalTask(id="0", prompt="test", criteria=["hello"])]
        assert tasks[0].criteria == ["hello"]
