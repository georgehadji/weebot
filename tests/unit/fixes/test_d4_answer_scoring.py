"""D4: the answer scorers run when a gold answer exists (WEEBOT_SCORING_MODE).

ScoringPort was bound to PlanOutcomeScorer only. The exact-match, execution and
verifier scorers compare against an expected answer, which a live session never
has, so they were left unwired and the harness's benchmark samples (which carry
expected answers) were scored by token overlap alone. Now an AnswerScorer sends a
session with an expected answer to the scorer the mode names, and every other
session to PlanOutcomeScorer as before.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from weebot.domain.models.benchmark_task import SamplePair, WeebotTask
from weebot.domain.models.session import Session


def _scored(value):
    return SimpleNamespace(score=value)


async def test_an_expected_answer_goes_to_the_answer_scorer():
    from weebot.infrastructure.scoring.answer_scorer import AnswerScorer

    answer = SimpleNamespace(score=AsyncMock(return_value=_scored(1.0)))
    fallback = SimpleNamespace(score=AsyncMock(return_value=_scored(0.4)))
    scorer = AnswerScorer(answer_scorer=answer, fallback=fallback)
    session = Session(id="s", user_id="u", agent_id="a")

    assert (await scorer.score(session, expected_answer="42")).score == 1.0
    assert (await scorer.score(session)).score == 0.4
    answer.score.assert_awaited_once_with(session, expected_answer="42")


def test_the_mode_picks_the_scorer(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di import Container
    from weebot.infrastructure.scoring.answer_scorer import AnswerScorer
    from weebot.infrastructure.scoring.exact_match_scorer import ExactMatchScorer
    from weebot.infrastructure.scoring.plan_outcome_scorer import PlanOutcomeScorer

    container = Container()
    monkeypatch.delenv("WEEBOT_SCORING_MODE", raising=False)
    importlib.reload(flags)
    assert type(container._create_scoring_port()) is PlanOutcomeScorer

    monkeypatch.setenv("WEEBOT_SCORING_MODE", "exact")
    importlib.reload(flags)
    try:
        scorer = container._create_scoring_port()
        assert isinstance(scorer, AnswerScorer)
        assert isinstance(scorer._answer_scorer, ExactMatchScorer)
    finally:
        monkeypatch.delenv("WEEBOT_SCORING_MODE")
        importlib.reload(flags)


async def test_benchmark_samples_with_an_answer_use_the_answer_scorer():
    from weebot.application.harness.runner import BenchmarkRunner

    def factory(session):
        async def run(_prompt):
            if False:
                yield None

        return SimpleNamespace(run=run, _session=session)

    answer = SimpleNamespace(score=AsyncMock(return_value=_scored(0.9)))
    task = WeebotTask(
        task_id="t", description="", samples=(SamplePair(prompt="p", expected_answer="42"),)
    )
    result = await BenchmarkRunner(flow_factory=factory, answer_scorer=answer).run_task(task)
    assert result.score == 0.9 and result.passed
    assert answer.score.await_args.kwargs == {"expected_answer": "42"}


def test_the_benchmark_commands_pass_the_scoring_port():
    from pathlib import Path

    src = Path("cli/commands/harness.py").read_text(encoding="utf-8")
    assert src.count("answer_scorer=_answer_scorer(container)") == 2
