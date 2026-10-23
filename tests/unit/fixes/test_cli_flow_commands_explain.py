"""`flow cancel` reaches other processes; `flow retry` says why it did nothing (F77).

Both act on state held only by the process that runs the session (TaskRunner's
task map and cached flow factory). From a fresh CLI process they could never
succeed, and the messages ("was not active", "no flow factory cached") did not
say that or where it does work.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from cli.commands.flow import flow


def test_cancel_files_a_request_for_a_run_in_another_process(tmp_path, monkeypatch):
    from weebot.core import cancel_requests
    from weebot.domain.models.session import Session, SessionStatus

    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    runner = MagicMock()
    runner.cancel_session = AsyncMock(return_value=False)
    repo = MagicMock()
    # WAITING: a resumed run keeps that status in the store while it works.
    repo.load_session = AsyncMock(return_value=Session(id="s1", status=SessionStatus.WAITING))
    repo.update_session_status = AsyncMock()
    with patch("cli.commands.flow.AgentRunner", return_value=runner),          patch("cli.commands.flow.ModelSelectionService"),          patch("cli.commands.flow._get_state_repo", return_value=repo):
        out = CliRunner().invoke(flow, ["cancel", "s1"]).output
    assert "Cancel requested" in out and cancel_requests.take("s1")


def test_retry_explains_the_same():
    task_runner = MagicMock()
    task_runner.rerun_failed_session = AsyncMock(return_value=False)
    container = MagicMock()
    container.get.return_value = task_runner
    with patch("weebot.interfaces.factories.shared_container", return_value=container), \
         patch("cli.commands.flow._container", None):
        out = CliRunner().invoke(flow, ["retry", "s1"]).output
    assert "process" in out and "web" in out
