"""Workflow memory (AWM) learns from a finished run, keeps it, and feeds the first plan.

Before: ``induce()`` refused RUNNING sessions and CompletedState called it before the
status was set, so nothing was ever induced; the store was an in-memory list that died
with the flow; and the hints reached only the replanner, never the first plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from weebot.application.services.workflow_memory import AgentWorkflowMemory, WorkflowTemplate
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session, SessionContext, SessionStatus
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

TASK = "build a responsive marketing website"


class _Llm:
    async def chat(self, **_):
        body = {"summary": "build marketing website", "steps": ["scaffold site", "style pages"]}
        return SimpleNamespace(content=json.dumps(body))


def _plan():
    return Plan(
        title=TASK,
        steps=[
            Step(id="1", description="scaffold", status=StepStatus.COMPLETED),
            Step(id="2", description="style", status=StepStatus.COMPLETED),
        ],
    )


@pytest.fixture
async def repo(tmp_path):
    r = SQLiteStateRepository(db_path=str(tmp_path / "awm.db"))
    await r._init_helpers()
    yield r
    await r.close()


async def test_a_run_that_is_still_marked_running_is_induced_from_its_plan():
    session = Session(id="s1", task=TASK, context=SessionContext(original_task=TASK))
    session = session.set_status(SessionStatus.RUNNING)
    template = await AgentWorkflowMemory(llm=_Llm()).induce(session, plan=_plan())
    assert template is not None and template.generalized_steps == ["scaffold site", "style pages"]


async def test_templates_survive_a_new_memory(repo):
    first = AgentWorkflowMemory(llm=_Llm(), store=repo)
    await first.store(WorkflowTemplate("build marketing website", ["scaffold site", "style pages"]))

    second = AgentWorkflowMemory(llm=_Llm(), store=repo)
    found = await second.query("build a marketing website for a bakery")
    assert found and found[0].generalized_steps == ["scaffold site", "style pages"]


async def test_the_repository_round_trips_a_template(repo):
    await repo.save_workflow_template("build marketing website", '{"task_summary": "x"}')
    await repo.save_workflow_template("build marketing website", '{"task_summary": "y"}')
    assert await repo.list_workflow_templates() == ['{"task_summary": "y"}']


def test_the_flow_memory_is_backed_by_the_state_repository():
    from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
    from weebot.application.models.tool_collection import ToolCollection

    flow = PlanActFlow(
        PlanActFlowConfig(llm=_Llm(), tools=ToolCollection(), session=Session(id="s2"))
    )
    flow._state_repo = object()
    assert flow._get_awm()._store is flow._state_repo


async def test_the_first_planner_receives_the_hints(monkeypatch, repo):
    from weebot.application.agents import planner as planner_mod
    from weebot.application.cqrs.commands import CreatePlanCommand
    from weebot.application.cqrs.handlers.create_plan_handler import CreatePlanHandler

    seen = {}

    class _StubPlanner:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def create_plan(self, prompt, meta_notes=None):
            return
            yield  # pragma: no cover

    monkeypatch.setattr(planner_mod, "PlannerAgent", _StubPlanner)
    await repo.save_session(Session(id="s3", task=TASK))
    result = await CreatePlanHandler(state_repo=repo, llm=_Llm()).handle(
        CreatePlanCommand(session_id="s3", prompt=TASK, awm_hints=["scaffold site"])
    )
    assert result.success, result.error
    assert seen.get("awm_hints") == ["scaffold site"]


def test_planning_sends_the_hints_with_the_first_plan_command():
    src = Path("weebot/application/flows/states/planning.py").read_text(encoding="utf-8")
    start = src.index("CreatePlanCommand(\n")
    assert "awm_hints=" in src[start : start + 600]
