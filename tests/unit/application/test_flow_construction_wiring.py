"""Every flow the product builds must have what a flow cannot run without.

Phase 2.1 of ``tasks/specs/arch_audit_2026_09_remediation_plan.md``.

Since 2b6f679 (2026-06-06) ``PlanningState`` refuses to run without a
mediator. Two construction paths never passed one:

* ``TaskRunner.create_plan_act_factory`` -- the only way the web API starts a
  task, used by the sessions router and ``dispatch_session_input``. Every
  web-started session emitted "PlanningState requires a Mediator" and planned
  nothing.
* ``CronAgentRunner`` -- every scheduled agent job, which also asked the
  container for two string keys nothing registers, and wrapped an async
  generator in ``asyncio.wait_for``.

Both stayed green because the tests on those paths mocked the factory:
``create_plan_act_factory = MagicMock(return_value=lambda s: MagicMock())``.
A mocked factory proves the caller calls a factory. It cannot prove the
factory builds something that runs. These tests build the real thing.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.cqrs.commands import CreatePlanCommand, ExecuteStepCommand
from weebot.application.cqrs.mediator import Mediator
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.session import Session

# Container construction imports the whole application -- 20-30s cold on
# Windows, past the suite's 60s per-test default once configure_defaults runs.
# Build it once for the module.


@pytest.fixture(scope="module")
def container():
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    return c


def _assert_can_plan_and_execute(flow, container):
    mediator = container.get(Mediator)
    assert flow._mediator is mediator, (
        "flow has no mediator -- PlanningState will refuse to run "
        "('PlanningState requires a Mediator')"
    )
    # A mediator with no handlers for these is the same failure one step later.
    for command in (CreatePlanCommand, ExecuteStepCommand):
        assert command in mediator._command_handlers, f"no handler for {command.__name__}"
    assert flow._state_repo is not None


@pytest.mark.timeout(360)
def test_a_web_started_session_gets_a_flow_that_can_plan(container):
    """The path the sessions router and dispatch_session_input both take."""
    from weebot.application.services.task_runner import TaskRunner

    runner = container.get(TaskRunner)
    factory = runner.create_plan_act_factory(llm=MagicMock(), tools=ToolCollection())

    flow = factory(Session(id="web-1", user_id="u", agent_id="a"))

    _assert_can_plan_and_execute(flow, container)


@pytest.mark.timeout(360)
def test_the_containers_flow_builder_supplies_the_mediator(container):
    """What CronAgentRunner calls. It passes no mediator; the builder must."""
    build = container.get("create_flow")

    flow = build(
        flow_type="plan_act",
        session=Session(id="cron-1", user_id="cron-agent", agent_id="cron-agent"),
        llm=MagicMock(),
        tools=ToolCollection(),
    )

    _assert_can_plan_and_execute(flow, container)


@pytest.mark.timeout(360)
def test_an_explicit_mediator_still_wins(container):
    build = container.get("create_flow")
    mine = MagicMock()

    flow = build(
        flow_type="plan_act",
        session=Session(id="x", user_id="u", agent_id="a"),
        llm=MagicMock(),
        tools=ToolCollection(),
        mediator=mine,
    )

    assert flow._mediator is mine


@pytest.mark.timeout(360)
def test_a_sub_agent_flow_can_plan(container):
    """The third construction site with the mediator defect.

    The tool registry falls back to container._build_plan_act_flow_for_session
    as the flow factory for debate, swarm, dispatch_parallel_tasks and
    workflow_orchestrator. It built PlanActFlowConfig with no mediator and
    asked for "state_repo" by string, so every sub-agent those tools spawned
    was refused by PlanningState. The DI census could not see it: the tool
    registry reaches the method by calling it, not by resolving a key.
    """
    flow = container._build_plan_act_flow_for_session(
        Session(id="sub-1", user_id="dispatch_agents", agent_id="a")
    )

    _assert_can_plan_and_execute(flow, container)


def test_a_task_runner_without_a_builder_refuses_rather_than_building_a_broken_flow():
    from weebot.application.services.task_runner import TaskRunner

    runner = TaskRunner(state_repo=AsyncMock())
    with pytest.raises(RuntimeError, match="no flow builder"):
        runner.create_plan_act_factory(llm=MagicMock(), tools=ToolCollection())


# ═════════════════════════════════════════════════════════════════════════════
# Cron
# ═════════════════════════════════════════════════════════════════════════════


class _AnsweringFlow:
    async def run(self, prompt: str):
        await asyncio.sleep(0)
        yield MagicMock(type="message", message="the answer")


def _job(**overrides):
    from weebot.domain.models.cron_job import CronJobRecord

    fields = dict(id="job-1", name="t", schedule="* * * * *", prompt="do the thing")
    fields.update(overrides)
    return CronJobRecord(**fields)


@pytest.mark.asyncio
async def test_a_cron_job_returns_the_flows_answer_not_a_type_error():
    """`async for ... in asyncio.wait_for(async_gen)` raised TypeError before
    the first event, and the handler turned it into the job's output -- which
    the delivery service then sent on as though it were a result."""
    from weebot.application.services.cron_agent_runner import CronAgentRunner

    runner = CronAgentRunner(
        llm=MagicMock(), state_repo=AsyncMock(), flow_factory=lambda **kw: _AnsweringFlow()
    )

    result = await runner.run(_job())

    assert result == "the answer", result


@pytest.mark.asyncio
async def test_a_cron_job_still_times_out():
    from weebot.application.services.cron_agent_runner import CronAgentRunner

    class _SlowFlow:
        async def run(self, prompt):
            await asyncio.sleep(10)
            yield MagicMock(type="message", message="too late")

    runner = CronAgentRunner(
        llm=MagicMock(), state_repo=AsyncMock(), flow_factory=lambda **kw: _SlowFlow()
    )
    job = _job()
    object.__setattr__(job, "max_runtime_seconds", 0.05)  # below the model's floor, on purpose

    result = await runner.run(job)

    assert "timed out" in result


class _FlagReportingFlow:
    """Reports what a tool running inside the job would see."""

    async def run(self, prompt: str):
        from weebot.core.cron_context import in_cron_job

        yield MagicMock(type="message", message=f"in_cron_job={in_cron_job()}")


@pytest.mark.asyncio
async def test_the_cron_flag_covers_the_job_and_ends_with_it():
    """The recursion guard's flag used to be os.environ["WEEBOT_CRON_CONTEXT"],
    set by every job and never cleared. The scheduler runs jobs in the web
    server's process, so after the first job scheduling would have been
    disabled for every user until a restart. It surfaced as eight
    ScheduleTool tests failing in CI after a cron test ran in the same
    process."""
    import os

    from weebot.application.services.cron_agent_runner import CronAgentRunner
    from weebot.core.cron_context import in_cron_job

    runner = CronAgentRunner(
        llm=MagicMock(), state_repo=AsyncMock(), flow_factory=lambda **kw: _FlagReportingFlow()
    )

    result = await runner.run(_job())

    assert result == "in_cron_job=True", "the flag did not reach the job's own flow"
    assert in_cron_job() is False, "the flag outlived the job"
    assert "WEEBOT_CRON_CONTEXT" not in os.environ


@pytest.mark.asyncio
async def test_the_schedule_tool_refuses_only_inside_a_cron_job():
    """The guard still works where it should, and nowhere else."""
    from weebot.core.cron_context import cron_job_context
    from weebot.tools.schedule_tool import ScheduleTool

    tool = ScheduleTool()
    with cron_job_context():
        inside = await tool.execute(action="not_an_action")
    outside = await tool.execute(action="not_an_action")

    assert "disabled inside a cron agent session" in (inside.error or "")
    assert "disabled inside a cron agent session" not in (outside.error or "") + (
        outside.output or ""
    )


@pytest.mark.timeout(360)
def test_the_keys_the_cron_paths_resolve_are_registered(container):
    """scheduler.py and cli/commands/cron_agent.py resolved "llm_port" and
    "state_repo_port". Both ports are bound by type; the strings resolve to
    nothing, and Container.get() raised KeyError on every run."""
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort

    assert container.get(LLMPort) is not None
    assert container.get(StateRepositoryPort) is not None
    for missing in ("llm_port", "state_repo_port", "mediator"):
        with pytest.raises(KeyError):
            container.get(missing)


# ═════════════════════════════════════════════════════════════════════════════
# The idea gate
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.timeout(360)
def test_the_containers_idea_gate_is_fully_built(container):
    from weebot.application.services.idea_gate import IdeaGate

    gate = container.get("idea_gate")

    assert isinstance(gate, IdeaGate)
    assert gate._intent_reviewer is not None
    assert gate._main_reviewer is not None


def test_the_idea_gate_is_built_only_by_the_container():
    """The "idea_gate" binding gives the intent reviewer the critic tier and the
    main reviewer the verifier tier. Three sites -- two in CompletedState, one
    in the dream CLI -- assembled the gate by hand on the default LLMPort
    instead, so the binding was never resolved. They take it from the
    container now; this keeps a fourth from appearing.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    builders = []
    for base in ("weebot", "cli"):
        for path in (root / base).rglob("*.py"):
            if "__pycache__" in path.parts or "GitNexus-main" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith("weebot/application/di/"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "IdeaGate"
                ):
                    builders.append(f"{rel}:{node.lineno}")
    assert builders == [], "IdeaGate built outside the container:\n  " + "\n  ".join(builders)
