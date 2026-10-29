"""D4: `harness baseline --judge` scores answers with EvalRunner and ModelJudge.

The baseline counted a task as passed when its flow did not fail, so it measured
completion, not quality; the judge and runner that score quality had no caller.
They also had three defects: a fenced judge reply scored 0, a task whose run raised
was still sent to the judge, and per-criterion averages came out on 0-10 while the
overall score is 0-1.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from weebot.application.eval.eval_runner import EvalRunner, EvalTask
from weebot.application.eval.judges import ModelJudge, ScoreJudge
from weebot.application.ports.judge_port import JudgeVerdict


async def test_a_fenced_judge_reply_is_scored():
    reply = '```json\n{"criteria": [], "overall_score": 8, "reasoning": "ok"}\n```'
    llm = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(content=reply)))
    verdict = await ModelJudge(llm=llm).judge("t", "out", [])
    assert verdict.overall_score == 0.8 and verdict.passed


async def test_a_task_whose_run_raised_is_not_judged():
    judge = SimpleNamespace(judge=AsyncMock())

    async def boom(_prompt):
        raise RuntimeError("no model")

    report = await EvalRunner(judge=judge).run(boom, [EvalTask(id="t1", prompt="p")])
    judge.judge.assert_not_awaited()
    result = report.results[0]
    assert result.score == 0.0 and not result.passed and "no model" in result.error


async def test_per_criterion_averages_use_the_overall_scale():
    async def target(_prompt):
        return "hello world"

    report = await EvalRunner(judge=ScoreJudge()).run(
        target, [EvalTask(id="t1", prompt="p", criteria=["hello"])]
    )
    assert report.per_criterion["hello"] == 1.0


def _flow_factory(answer: str, status: str = "completed"):
    def factory(session):
        async def run(_prompt):
            session.events.append(SimpleNamespace(role="assistant", message=answer))
            session.status = status
            if False:
                yield None

        return SimpleNamespace(run=run, _session=session)

    return factory


async def test_with_a_judge_the_baseline_scores_the_answer():
    from cli.commands.harness import _score_tasks

    judge = SimpleNamespace(
        judge=AsyncMock(return_value=JudgeVerdict(overall_score=0.3, passed=False, reasoning="x"))
    )
    [outcome] = await _score_tasks(
        [("t1", "held_in", "say hi")], _flow_factory("hi"), concurrency=1, judge=judge
    )
    assert judge.judge.await_args.kwargs["output"] == "hi"
    assert outcome.passed is False and outcome.score == 0.3


async def test_without_a_judge_the_baseline_still_measures_completion():
    from cli.commands.harness import _score_tasks

    [ok] = await _score_tasks([("t1", "held_in", "p")], _flow_factory("a"), concurrency=1)
    [bad] = await _score_tasks(
        [("t2", "held_in", "p")], _flow_factory("a", status="failed"), concurrency=1
    )
    assert ok.passed and ok.score == 1.0
    assert not bad.passed
