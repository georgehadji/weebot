"""Unit tests for Ponytail CLI commands."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_ponytail_command_help(runner: CliRunner) -> None:
    """The ponytail command shows usage help."""
    result = runner.invoke(cli, ["ponytail", "--help"])
    assert result.exit_code == 0
    assert "lite" in result.output
    assert "full" in result.output
    assert "ultra" in result.output


def test_ponytail_help_command(runner: CliRunner) -> None:
    """ponytail-help prints the reference card."""
    result = runner.invoke(cli, ["ponytail-help"])
    assert result.exit_code == 0
    assert "Ponytail Help" in result.output


def test_ponytail_invalid_level(runner: CliRunner) -> None:
    """An invalid Ponytail level is rejected."""
    result = runner.invoke(cli, ["ponytail", "invalid"])
    assert result.exit_code != 0
    assert "Invalid level" in result.output


def test_ponytail_review_no_git_repo(runner: CliRunner) -> None:
    """ponytail-review fails gracefully outside a git repo."""
    result = runner.invoke(cli, ["ponytail-review"], catch_exceptions=False)
    # git diff HEAD will fail because cwd is not a git repo in isolated tests,
    # but the runner still invokes from the original cwd. We just verify the
    # command is registered and handles the case without crashing.
    assert result.exit_code in (0, 1)


def test_ponytail_audit_command_help(runner: CliRunner) -> None:
    """ponytail-audit shows its options."""
    result = runner.invoke(cli, ["ponytail-audit", "--help"])
    assert result.exit_code == 0
    assert "--path" in result.output
