"""A20 / D3a: a shell segment that matches no rule used to be approved. It now asks unless it
is a plain read. Observe mode (the default) only records what would have asked."""

from __future__ import annotations

import logging

import pytest

from weebot.application.services.tool_guards import ApprovalPolicyAdapter, GuardAction
from weebot.core.approval_policy import ExecApprovalPolicy


def _unmatched(command: str) -> list[str]:
    return ExecApprovalPolicy().unreviewed_segments(command)


@pytest.mark.parametrize("command", [
    "Get-ChildItem C:/Users",
    "ls -la",
    "cat notes.txt",
    "git status",
    "git log --oneline -5",
    "git diff HEAD~1",
    "Select-String -Path a.txt -Pattern x",
    "Test-Path Output/x",
    "Get-Process | Select-Object Name",
    "grep -rn foo src",
    "Write-Output hello",
])
def test_plain_reads_are_not_flagged(command):
    assert _unmatched(command) == []


@pytest.mark.parametrize("command,expected", [
    ("[IO.Directory]::Delete('C:/x', $true)", ["[IO.Directory]::Delete('C:/x', $true)"]),
    ("mytool.exe --go", ["mytool.exe --go"]),
    ("Get-Process | Foo-Bar x", ["Foo-Bar x"]),
    ("ls; curl http://x", ["curl http://x"]),
    ("Get-Content a.txt > b.txt", ["Get-Content a.txt > b.txt"]),
    ("git push origin main", ["git push origin main"]),
    ("git status; git reset --hard", ["git reset --hard"]),
])
def test_everything_else_with_no_rule_is_flagged(command, expected):
    assert _unmatched(command) == expected


def test_a_segment_a_rule_already_covers_is_not_double_counted():
    assert _unmatched("Remove-Item C:/x -Recurse") == []  # the destructive rule asks already


def test_the_output_carve_out_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Output").mkdir()
    assert _unmatched("Set-Content Output/a.txt hello") == []


@pytest.fixture
def mode(monkeypatch):
    from weebot.config.settings import get_settings

    def _set(value):
        monkeypatch.setattr(get_settings(), "shell_default_ask", value, raising=False)

    return _set


def test_enforce_asks(mode):
    mode("enforce")
    verdict = ApprovalPolicyAdapter().check("powershell", {"command": "mytool.exe --go"})
    assert verdict is not None and verdict.action is GuardAction.ASK


def test_observe_records_and_lets_it_through(mode, caplog):
    mode("observe")
    with caplog.at_level(logging.WARNING):
        assert ApprovalPolicyAdapter().check("bash", {"command": "mytool.exe --go"}) is None
    assert any("shell_default_ask would ask" in r.getMessage() for r in caplog.records)


def test_off_is_silent(mode, caplog):
    mode("off")
    with caplog.at_level(logging.WARNING):
        assert ApprovalPolicyAdapter().check("bash", {"command": "mytool.exe --go"}) is None
    assert not any("shell_default_ask" in r.getMessage() for r in caplog.records)


def test_python_execute_is_never_flagged(mode):
    mode("enforce")
    assert ApprovalPolicyAdapter().check("python_execute", {"code": "executor.shutdown()"}) is None


def test_a_read_only_shell_call_is_untouched_in_enforce(mode):
    mode("enforce")
    assert ApprovalPolicyAdapter().check("bash", {"command": "git status"}) is None
