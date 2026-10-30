"""L5 (remaining-work plan 2026-10-29): ``flow retry`` can rerun a failed session.

``rerun_failed_session`` looked for the flow factory in the retry state, which
``_cleanup`` drops when the run ends, so it always returned False. The old test seeded
that state by hand and hid it. The caller now passes the factory, as ``resume_session``
takes one, so a rerun also works in a fresh process.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from tests.unit.application.services.test_task_runner_durable_state import (
    ExplodingFlow,
    MemoryRepo,
    _run_to_failure,
    _settle,
    no_backoff,  # noqa: F401 - autouse fixture
)
from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.session import Session, SessionStatus


@pytest.mark.asyncio
async def test_a_failed_run_reruns_in_a_fresh_runner():
    repo = MemoryRepo()
    await _run_to_failure(TaskRunner(state_repo=repo, max_session_retries=1), repo, "x")
    assert repo.sessions["x"].status == SessionStatus.FAILED

    flows: list[ExplodingFlow] = []

    def factory(session):
        flows.append(ExplodingFlow(session))
        return flows[-1]

    fresh = TaskRunner(state_repo=repo, max_session_retries=1)  # a new process
    assert await fresh.rerun_failed_session("x", factory) is True
    await _settle(fresh, "x")
    assert flows, "the rerun ran the flow"


@pytest.mark.asyncio
async def test_a_session_that_did_not_fail_is_not_rerun():
    repo = MemoryRepo()
    await repo.save_session(Session(id="ok", user_id="u", agent_id="a"))
    runner = TaskRunner(state_repo=repo)
    assert await runner.rerun_failed_session("ok", lambda s: ExplodingFlow(s)) is False


@pytest.mark.asyncio
async def test_wait_returns_once_the_run_and_its_retries_end():
    repo = MemoryRepo()
    runner = TaskRunner(state_repo=repo, max_session_retries=2)
    session = Session(id="w", user_id="u", agent_id="a")
    await repo.save_session(session)
    await runner.start_session(session, lambda s: ExplodingFlow(s))
    await runner.wait_for("w")
    assert await runner.list_active_sessions() == []
    assert repo.sessions["w"].status == SessionStatus.FAILED


def test_the_cli_builds_a_factory_and_waits():
    failed = Session(id="s1", status=SessionStatus.FAILED)
    task_runner = MagicMock()
    task_runner.rerun_failed_session = AsyncMock(return_value=True)
    task_runner.wait_for = AsyncMock()
    repo = MagicMock()
    repo.load_session = AsyncMock(return_value=failed)
    container = MagicMock()
    container.get.return_value = task_runner
    tools = MagicMock(teardown=AsyncMock())
    with patch("cli.commands.flow._get_container", return_value=container), \
         patch("cli.commands.flow._get_state_repo", return_value=repo), \
         patch("cli.commands.flow._cli_llm"), \
         patch("weebot.interfaces.factories.build_tools", AsyncMock(return_value=tools)):
        out = CliRunner().invoke(flow_cmd(), ["retry", "s1"]).output
    factory = task_runner.create_plan_act_factory.return_value
    task_runner.rerun_failed_session.assert_awaited_once_with("s1", factory)
    task_runner.wait_for.assert_awaited_once_with("s1")
    assert "Retrying" in out
    tools.teardown.assert_not_awaited()  # the flow owns the tools once it runs


def test_the_cli_tears_down_the_tools_when_nothing_reruns():
    task_runner = MagicMock()
    task_runner.rerun_failed_session = AsyncMock(return_value=False)
    repo = MagicMock()
    repo.load_session = AsyncMock(return_value=Session(id="s1", status=SessionStatus.COMPLETED))
    container = MagicMock()
    container.get.return_value = task_runner
    tools = MagicMock(teardown=AsyncMock())
    with patch("cli.commands.flow._get_container", return_value=container), \
         patch("cli.commands.flow._get_state_repo", return_value=repo), \
         patch("cli.commands.flow._cli_llm"), \
         patch("weebot.interfaces.factories.build_tools", AsyncMock(return_value=tools)):
        out = CliRunner().invoke(flow_cmd(), ["retry", "s1"]).output
    assert "not FAILED" in out
    tools.teardown.assert_awaited_once()


def flow_cmd():
    from cli.commands.flow import flow

    return flow
