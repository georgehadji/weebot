"""Live-session trajectory scoring, end to end.

CompletedState sends ScoreTrajectoryCommand after every flow. Before this,
four separate things stopped it from ever doing anything:

1. The main container looked the scorer up under "scoring_port", a string
   nothing registered, so ScoreTrajectoryHandler was never registered and
   every command failed with a logged warning.
2. SkillOpt passed the OPTIMIZER as the scorer. OptimizerAgent has no
   score(), so scoring failed there too.
3. The three existing scorers are benchmark scorers. Each compares against
   an expected answer a live session does not have, so wired to live
   sessions each would produce a constant, meaningless score.
4. The handler persisted to an event store nothing ever attached, and the
   learners read trajectories from the trajectory repository anyway.

These tests cover the scorer that replaces (3) and the wiring that replaces
(1), (2) and (4).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session
from weebot.infrastructure.scoring.plan_outcome_scorer import PlanOutcomeScorer


def _session(*statuses: StepStatus) -> Session:
    steps = [
        Step(id=f"s{i}", description=f"step {i}", status=status)
        for i, status in enumerate(statuses)
    ]
    return Session(id="sess").add_event(PlanEvent(plan=Plan(title="t", message="m", steps=steps)))


# ── The scorer ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_plan_that_succeeded_scores_one():
    scored = await PlanOutcomeScorer().score(_session(StepStatus.COMPLETED, StepStatus.COMPLETED))
    assert scored.score == 1.0
    assert scored.success_patterns == ["plan_succeeded"]
    assert scored.failure_modes == []


@pytest.mark.asyncio
async def test_a_plan_where_everything_failed_scores_zero_not_one():
    """is_complete() counts FAILED as done, so an all-failed plan is "complete".
    That confusion once scored an all-failed plan 1.0 and stored it for reuse.
    This scorer follows is_successful()."""
    scored = await PlanOutcomeScorer().score(_session(StepStatus.FAILED, StepStatus.FAILED))
    assert scored.score == 0.0
    assert scored.success_patterns == []
    assert all(m.startswith("step_failed") for m in scored.failure_modes)


@pytest.mark.asyncio
async def test_partial_success_scores_the_fraction_and_names_what_went_wrong():
    scored = await PlanOutcomeScorer().score(
        _session(StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.UNVERIFIED, StepStatus.COMPLETED)
    )
    assert scored.score == 0.5
    assert any(m.startswith("step_failed") for m in scored.failure_modes)
    assert any(m.startswith("step_unverified") for m in scored.failure_modes)


@pytest.mark.asyncio
async def test_unverified_is_not_success():
    """Executed, but the evidence did not support completion."""
    scored = await PlanOutcomeScorer().score(_session(StepStatus.UNVERIFIED))
    assert scored.score == 0.0


@pytest.mark.asyncio
async def test_a_session_without_a_plan_is_a_named_failure():
    scored = await PlanOutcomeScorer().score(Session(id="empty"))
    assert scored.score == 0.0
    assert scored.failure_modes == ["no_plan"]


@pytest.mark.asyncio
async def test_the_same_session_always_scores_the_same():
    session = _session(StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.COMPLETED)
    first = await PlanOutcomeScorer().score(session)
    second = await PlanOutcomeScorer().score(session)
    assert first.score == second.score


# ── The handler persists where the learners read ─────────────────────────────


@pytest.mark.asyncio
async def test_the_handler_stores_the_trajectory_in_the_repository():
    from weebot.application.cqrs.commands.trajectory_commands import ScoreTrajectoryCommand
    from weebot.application.cqrs.handlers.trajectory_handler import ScoreTrajectoryHandler

    session = _session(StepStatus.COMPLETED)
    state_repo = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=session)
    trajectory = MagicMock(passed=True)
    builder = MagicMock()
    builder.build = AsyncMock(return_value=trajectory)
    repo = AsyncMock()

    handler = ScoreTrajectoryHandler(
        PlanOutcomeScorer(), state_repo, builder, trajectory_repo=repo
    )
    result = await handler.handle(ScoreTrajectoryCommand(session_id="sess", harness="direct_chat"))

    assert result.success, result.error
    repo.save.assert_awaited_once_with(trajectory)


# ── The main container actually registers it ─────────────────────────────────


@pytest.mark.timeout(360)
def test_the_main_container_can_handle_the_command_completed_state_sends():
    """The failure this whole file is about, at the level it happened.

    Before, ScoreTrajectoryCommand had no handler in the main container's
    mediator, so the send in CompletedState failed after every flow.
    """
    from weebot.application.cqrs.commands.trajectory_commands import ScoreTrajectoryCommand
    from weebot.application.cqrs.mediator import Mediator
    from weebot.application.di import Container

    container = Container()
    container.configure_defaults()
    handler = container.get(Mediator)._command_handlers.get(ScoreTrajectoryCommand)

    assert handler is not None, "no handler: every completed flow's scoring fails"
    assert isinstance(handler._scoring, PlanOutcomeScorer)
    assert handler._trajectory_repo is not None, "scored, then dropped"
    # No mediator: live sessions must not go on to pay for failure-signature
    # extraction on every low score.
    assert handler._mediator is None
