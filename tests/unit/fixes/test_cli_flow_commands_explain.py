"""`flow cancel` / `flow retry` say why they did nothing (F77).

Both act on state held only by the process that runs the session (TaskRunner's
task map and cached flow factory). From a fresh CLI process they could never
succeed, and the messages ("was not active", "no flow factory cached") did not
say that or where it does work.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from cli.commands.flow import flow


def test_cancel_explains_it_only_reaches_the_running_process():
    runner = MagicMock()
    runner.cancel_session = AsyncMock(return_value=False)
    with patch("cli.commands.flow.AgentRunner", return_value=runner), \
         patch("cli.commands.flow.ModelSelectionService"), \
         patch("cli.commands.flow._get_state_repo"):
        out = CliRunner().invoke(flow, ["cancel", "s1"]).output
    assert "/api/sessions/s1/cancel" in out


def test_retry_explains_the_same():
    task_runner = MagicMock()
    task_runner.rerun_failed_session = AsyncMock(return_value=False)
    container = MagicMock()
    container.get.return_value = task_runner
    with patch("weebot.interfaces.factories.shared_container", return_value=container), \
         patch("cli.commands.flow._container", None):
        out = CliRunner().invoke(flow, ["retry", "s1"]).output
    assert "process" in out and "web" in out
