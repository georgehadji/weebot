"""`flow cancel` reaches other processes (F77).

It acts on TaskRunner's task map, held only by the process that runs the session,
so from a fresh CLI process it could never succeed. (`flow retry` now builds its own
flow factory and runs in the CLI process: tests/unit/fixes/test_l5_rerun_failed_session.py.)
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
    with patch("cli.commands.flow.AgentRunner", return_value=runner), \
         patch("cli.commands.flow._get_container"), \
         patch("cli.commands.flow._get_state_repo", return_value=repo):
        out = CliRunner().invoke(flow, ["cancel", "s1"]).output
    assert "Cancel requested" in out and cancel_requests.take("s1")
