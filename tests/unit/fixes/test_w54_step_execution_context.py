"""W5.4 (F25, ADR-015): the executor that runs a step gets the flow's settings.

Steps run through ExecuteStepHandler on an executor the container's factory
builds from singletons only. The flow's role-scoped tools, skill prompt, role,
behavioral learner, harness block, middleware and trajectory config went to
`PlanActFlow._executor`, which never runs a step -- and the flow read token
usage and skill gaps from that idle executor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from weebot.application.cqrs.commands import ExecuteStepCommand
from weebot.application.cqrs.handlers.execute_step_handler import ExecuteStepHandler
from weebot.application.models.step_execution_context import StepExecutionContext
from weebot.domain.models.event import PlanEvent, StepEvent, StepStatus
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session


def _session() -> Session:
    plan = Plan(title="t", message="m", steps=[Step(id="s1", description="do it")])
    return Session(id="sess-1").add_event(PlanEvent(plan=plan))


class _Repo:
    async def load_session(self, session_id):
        return _session()


def _fake_executor(usage=None, gaps=None):
    async def _run(plan, step, user_input="", session_id=""):
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

    ex = AsyncMock()
    ex.execute_step = _run
    ex.token_usage = usage or {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    ex._skill_gaps = gaps or ["gap-1"]
    return ex


def test_the_context_keeps_only_what_the_flow_set():
    ctx = StepExecutionContext(skill_prompt="be brief", agent_role="coder")
    assert ctx.executor_kwargs() == {"skill_prompt": "be brief", "agent_role": "coder"}


def test_the_context_never_reaches_a_dump():
    cmd = ExecuteStepCommand(
        session_id="s", step_id="1", step_context=StepExecutionContext(agent_role="coder")
    )
    assert "step_context" not in cmd.model_dump()


@pytest.mark.asyncio
async def test_the_factory_receives_the_flow_context_and_usage_comes_back():
    seen = {}
    ex = _fake_executor()

    def _factory(*, model, session, context=None):
        seen["context"] = context
        return ex

    ctx = StepExecutionContext(agent_role="coder", skill_prompt="be brief")
    handler = ExecuteStepHandler(state_repo=_Repo(), executor_factory=_factory)
    result = await handler.handle(
        ExecuteStepCommand(session_id="sess-1", step_id="s1", step_context=ctx)
    )
    assert result.success and seen["context"] is ctx
    assert result.data["token_usage"]["total_tokens"] == 10
    assert result.data["skill_gaps"] == ["gap-1"]


@pytest.mark.asyncio
async def test_without_a_factory_the_context_still_reaches_the_executor(monkeypatch):
    captured = {}
    ex = _fake_executor()

    def _executor(**kw):
        captured.update(kw)
        return ex

    monkeypatch.setattr("weebot.application.agents.executor.ExecutorAgent", _executor)
    tools = object()
    handler = ExecuteStepHandler(state_repo=_Repo())
    await handler.handle(
        ExecuteStepCommand(
            session_id="sess-1",
            step_id="s1",
            step_context=StepExecutionContext(tools=tools, agent_role="coder"),
        )
    )
    assert captured["tools"] is tools and captured["agent_role"] == "coder"


def test_the_container_factory_overlays_the_context():
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    tools = object()
    ex = c.step_executor(
        model="m", session=_session(), context=StepExecutionContext(tools=tools, agent_role="coder")
    )
    assert ex._tools is tools and ex._agent_role == "coder"


@pytest.mark.asyncio
async def test_the_flow_sends_its_context_and_totals_step_usage():
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.tools.base import ToolCollection

    flow = PlanActFlow(llm=AsyncMock(), tools=ToolCollection(), session=_session())
    assert not hasattr(flow, "_executor") and hasattr(flow, "_summary_executor")
    ctx = flow.step_execution_context()
    assert ctx.tools is flow._tools

    flow.record_step_usage({"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}, ["g"])
    flow.record_step_usage({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, [])
    assert flow.token_usage["total_tokens"] >= 12
    assert flow.step_skill_gaps == ["g"]
