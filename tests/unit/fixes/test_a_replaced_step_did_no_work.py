"""A failed step that a plan update replaced is not counted as work that succeeded.

Found by review of the CoVe fix: UpdatingState marks the replaced step COMPLETED with
the result "Handled by plan update", and only VerifyingState knew to skip it.
``Plan.is_successful()`` (which gates plan templates and skill distillation) and the
trajectory scorer still counted it, so a plan whose step failed was saved for reuse
with a score of 1.0.
"""

from __future__ import annotations

from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import REPLACED_BY_PLAN_UPDATE, Plan, Step, StepStatus
from weebot.domain.models.session import Session
from weebot.infrastructure.scoring.plan_outcome_scorer import PlanOutcomeScorer


def _plan():
    return Plan(
        title="t",
        steps=[
            Step(
                id="s1", description="a", status=StepStatus.COMPLETED,
                result=REPLACED_BY_PLAN_UPDATE,
            ),
            Step(id="s2", description="b", status=StepStatus.COMPLETED, result="did b"),
        ],
    )


def test_the_replaced_step_did_no_work():
    replaced, real = _plan().steps
    assert not replaced.did_work() and real.did_work()


def test_a_plan_with_a_replaced_step_is_not_successful():
    assert not _plan().is_successful()


async def test_the_scorer_does_not_count_the_replaced_step():
    session = Session(id="s").add_event(PlanEvent(plan=_plan()))
    scored = await PlanOutcomeScorer().score(session)
    assert scored.score == 0.5
    assert "plan_succeeded" not in scored.success_patterns
