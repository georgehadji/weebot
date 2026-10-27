"""Past failures on similar tasks reach the planner.

Before: live runs saved a trajectory with a paid summary and nothing ever read it back;
the live trajectory handler had no mediator, so failed runs never got a failure
signature either. Now a trajectory keeps its task, failed ones are retrievable by task
similarity, and PlanningState hands the closest ones to the planner as notes.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.domain.models.trajectory import TrajectorySummary
from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository


@pytest.fixture
async def repo(tmp_path):
    r = TrajectoryRepository(db_path=str(tmp_path / "traj.db"))
    yield r


def _traj(session, task, passed, modes=("timeout on deploy",)):
    return TrajectorySummary(
        task_id=session,
        session_id=session,
        score=1.0 if passed else 0.0,
        passed=passed,
        failure_modes=list(modes),
        task_text=task,
    )


async def test_a_trajectory_keeps_its_task(repo):
    await repo.save(_traj("s1", "deploy the marketing site", passed=False))
    (got,) = await repo.get_by_session("s1")
    assert got.task_text == "deploy the marketing site"


async def test_only_failed_runs_come_back_as_failures(repo):
    await repo.save(_traj("s1", "deploy the marketing site", passed=False))
    await repo.save(_traj("s2", "deploy the marketing site", passed=True))
    assert [t.session_id for t in await repo.recent_failures()] == ["s1"]


async def test_similar_failures_become_planner_notes(repo):
    from weebot.application.services.failure_lessons import similar_failure_notes

    await repo.save(_traj("s1", "deploy the marketing site to netlify", passed=False))
    await repo.save(_traj("s2", "write a poem about cats", passed=False, modes=("rhyme",)))
    notes = await similar_failure_notes(repo, "deploy my marketing site")
    assert len(notes) == 1
    assert "timeout on deploy" in notes[0] and "poem" not in notes[0]


async def test_no_repository_means_no_notes():
    from weebot.application.services.failure_lessons import similar_failure_notes

    assert await similar_failure_notes(None, "anything") == []


async def test_the_live_handler_stores_the_task_and_asks_for_a_signature():
    from weebot.application.cqrs.commands.trajectory_commands import ScoreTrajectoryCommand
    from weebot.application.cqrs.handlers.trajectory_handler import ScoreTrajectoryHandler
    from weebot.domain.models.session import Session, SessionContext

    session = Session(id="s1", task="deploy", context=SessionContext(original_task="deploy it"))
    state_repo = SimpleNamespace(load_session=AsyncMock(return_value=session))
    scoring = SimpleNamespace(score=AsyncMock(return_value=SimpleNamespace(score=0.0, model_dump=dict)))
    builder = SimpleNamespace(build=AsyncMock(return_value=_traj("s1", "", passed=False)))
    trajectories = SimpleNamespace(save=AsyncMock())
    mediator = SimpleNamespace(send=AsyncMock())

    handler = ScoreTrajectoryHandler(
        scoring, state_repo, builder, mediator=mediator, trajectory_repo=trajectories
    )
    result = await handler.handle(ScoreTrajectoryCommand(session_id="s1"))
    assert result.success, result.error
    assert trajectories.save.await_args.args[0].task_text == "deploy it"
    mediator.send.assert_awaited_once()


def test_the_live_mediator_extracts_failure_signatures():
    from weebot.application.cqrs.commands.failure_signature_commands import (
        ExtractFailureSignatureCommand,
    )
    from weebot.application.cqrs.handlers import register_default_handlers
    from weebot.application.cqrs.mediator import Mediator

    mediator = Mediator()
    register_default_handlers(
        mediator,
        MagicMock(),
        llm=MagicMock(),
        scoring_port=MagicMock(),
        trajectory_builder=MagicMock(),
        trajectory_repo=MagicMock(),
    )
    assert ExtractFailureSignatureCommand in mediator._command_handlers


def test_planning_adds_the_past_failure_notes():
    src = Path("weebot/application/flows/states/planning.py").read_text(encoding="utf-8")
    assert "similar_failure_notes(" in src
