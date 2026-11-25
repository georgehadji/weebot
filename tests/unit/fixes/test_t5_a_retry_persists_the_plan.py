"""X5: a retry reset the step in the flow's memory only, and ExecuteStepHandler (which reads
the SAVED plan) refused it. Every retry path now goes through `retry_step`, which persists
the plan with an updated PlanEvent before the flow goes back to EXECUTING.
"""

from __future__ import annotations

from types import SimpleNamespace

from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states._step_outcome import quality_gate, route_failure
from weebot.application.flows.states._step_run import StepRun
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.reviewing import ReviewingState
from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.event import ErrorEvent, PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step, StepStatus
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


async def _flow():
    repo = InMemoryStateRepository()
    session = Session(id="s1", user_id="u", agent_id="a", status=SessionStatus.RUNNING)
    await repo.save_session(session)
    flow = PlanActFlow(session=session, state_repo=repo)
    flow._plan = Plan(
        title="t", steps=[Step(id="s1", description="do it", status=StepStatus.RUNNING)]
    )
    return flow, repo


async def _saved_step(repo):
    plan = (await repo.load_session("s1")).get_last_plan()
    return next(s for s in plan.steps if s.id == "s1")


async def test_a_minor_failure_retry_is_in_the_saved_plan():
    flow, repo = await _flow()
    run = StepRun(events=[ErrorEvent(error="request timed out")])

    assert await route_failure(flow, flow._plan.steps[0], run) is None

    saved = await _saved_step(repo)
    assert saved.status == StepStatus.PENDING and saved.retry_count == 1
    assert isinstance(flow._state, ExecutingState)


async def test_a_quality_retry_is_in_the_saved_plan(monkeypatch):
    from weebot.application.services.step_result_validator import ValidationResult

    monkeypatch.setattr(
        "weebot.application.services.step_result_validator.StepResultValidator.validate",
        lambda *a, **k: ValidationResult(passed=False, reason="too short", quality_hint="expand"),
    )
    flow, repo = await _flow()

    assert await quality_gate(flow, flow._plan.steps[0], StepRun(result_text="x")) is True

    saved = await _saved_step(repo)
    assert saved.status == StepStatus.PENDING and saved.retry_count == 1
    assert "[Quality hint: expand]" in saved.description


async def test_a_review_revise_is_in_the_saved_plan_and_yielded():
    flow, repo = await _flow()
    step = flow._plan.steps[0].model_copy(update={"status": StepStatus.COMPLETED})
    flow._plan = flow._plan.replace_step("s1", step)
    result = CodeReviewResult(verdict="revise", summary="s", hint="use fewer files")

    async def review(_step, _context):
        return result

    state = ReviewingState(step=step, reviewer=SimpleNamespace(review=review), step_events=[])
    events = [e async for e in state.execute(flow, "go")]

    saved = await _saved_step(repo)
    assert saved.status == StepStatus.PENDING and saved.retry_count == 1
    assert "[Code review hint: use fewer files]" in saved.description
    assert [e.status for e in events if isinstance(e, PlanEvent)] == [PlanStatus.UPDATED]
