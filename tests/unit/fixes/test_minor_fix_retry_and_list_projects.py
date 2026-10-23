"""Two crashes the map re-verification found by reading the code (2026-10-24).

- `ExecutingState`'s minor_fix retry called `Plan.update_step`, which `Plan`
  does not have, so the one retry a timeout earns raised AttributeError.
  `Plan.replace_step` is the existing API for it.
- `cli list-projects` read `session.session_id`; `Session` calls it `id`.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from weebot.application.cqrs.base import CommandResult
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.plan import Plan, Step, StepStatus


class _LLM:
    async def chat(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("not called")


class _TimedOut:
    async def send(self, _command):
        return CommandResult(
            success=True, data={"events": [ErrorEvent(error="Request timed out").model_dump()]}
        )


@pytest.mark.asyncio
async def test_a_timed_out_step_is_requeued_once():
    from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
    from weebot.application.flows.states.executing import ExecutingState
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session

    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(), tools=ToolCollection(), session=Session(id="s", task="t"),
            max_iterations=1,
        )
    )
    flow._plan = Plan(goal="g", steps=[Step(id="s0", description="fetch")])
    flow._mediator = _TimedOut()

    async for _ in ExecutingState().execute(flow, "t"):
        pass

    step = flow._plan.steps[0]
    assert step.status == StepStatus.PENDING
    assert step.retry_count == 1
    assert isinstance(flow._state, ExecutingState)


def test_list_projects_shows_session_ids(monkeypatch):
    import cli.main as cli_main
    from weebot.domain.models.session import Session

    class _Repo:
        async def list_sessions(self):
            return [Session(id="sess-42", task="t")]

    monkeypatch.setattr(cli_main, "_get_state_repo", lambda: _Repo())
    result = CliRunner().invoke(cli_main.cli, ["list-projects"])
    assert result.exception is None, result.output
    assert "sess-42" in result.output
