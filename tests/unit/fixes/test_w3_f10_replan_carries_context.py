"""F10: the replan command carries typed context, and the handler uses it.

`UpdatingState` put `failure_context` and `last_step_id` in an untyped `updates` dict. The
handler never read either: it chose its own step and called the planner with no failure text,
so the tree-of-thoughts calls were paid for and discarded. They are typed fields now, and a
misspelt one fails at construction (`Command` forbids extra fields).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from weebot.application.cqrs.commands import UpdatePlanCommand
from weebot.application.cqrs.handlers import UpdatePlanHandler
from weebot.domain.models.event import PlanEvent, PlanStatus
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


class _RecordingPlanner:
    calls: list[tuple[str, str]] = []

    def __init__(self, *a, **k):
        pass

    async def update_plan(self, plan, completed_step, failure_context=""):
        type(self).calls.append((completed_step.id, failure_context))
        return
        yield  # an async generator that emits nothing


@pytest.fixture
def planner(monkeypatch):
    import weebot.application.agents.planner as planner_module

    _RecordingPlanner.calls = []
    monkeypatch.setattr(planner_module, "PlannerAgent", _RecordingPlanner)
    return _RecordingPlanner


async def _repo_with_plan() -> InMemoryStateRepository:
    plan = Plan(
        title="p",
        message="m",
        steps=[
            Step(id="s1", description="done one", status="completed"),
            Step(id="s2", description="broke", status="failed", result="boom"),
            Step(id="s3", description="later", status="pending"),
        ],
    )
    session = Session(id="sess", user_id="u").add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump())
    )
    repo = InMemoryStateRepository()
    await repo.save_session(session)
    return repo


async def test_the_planner_gets_the_failure_text_and_the_chosen_step(planner):
    repo = await _repo_with_plan()
    handler = UpdatePlanHandler(state_repo=repo, llm=object())
    result = await handler.handle(
        UpdatePlanCommand(
            session_id="sess", last_step_id="s2", failure_context="boom: tool blocked"
        )
    )
    assert result.success, result.error
    assert planner.calls == [("s2", "boom: tool blocked")]


async def test_without_an_id_the_last_finished_step_is_used_as_before(planner):
    repo = await _repo_with_plan()
    handler = UpdatePlanHandler(state_repo=repo, llm=object())
    await handler.handle(UpdatePlanCommand(session_id="sess", reason="retry"))
    assert planner.calls == [("s2", "")]


async def test_an_unknown_step_id_is_an_error_not_a_guess(planner):
    repo = await _repo_with_plan()
    handler = UpdatePlanHandler(state_repo=repo, llm=object())
    result = await handler.handle(UpdatePlanCommand(session_id="sess", last_step_id="nope"))
    assert not result.success
    assert result.error_code == "STEP_NOT_FOUND"
    assert planner.calls == []


def test_the_context_is_a_typed_field_and_a_misspelling_fails_at_construction():
    cmd = UpdatePlanCommand(session_id="s", failure_context="x", last_step_id="s2")
    assert (cmd.failure_context, cmd.last_step_id) == ("x", "s2")
    assert UpdatePlanCommand(session_id="s").failure_context == ""
    with pytest.raises(ValidationError):
        UpdatePlanCommand(session_id="s", failure_contxt="x")
    with pytest.raises(ValidationError):
        UpdatePlanCommand(session_id="s", updates={"failure_context": "x"})
