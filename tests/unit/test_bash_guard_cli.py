"""Unit tests for the guard CLI command."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from cli.commands.guard import guard


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestGuardCheck:
    """Tests for `guard check` command."""

    def test_safe_command(self, runner: CliRunner) -> None:
        """A safe command should exit 0 and report SAFE."""
        result = runner.invoke(guard, ["check", "--command", "echo hello"])
        assert result.exit_code == 0
        assert "SAFE" in result.output

    def test_suspicious_command(self, runner: CliRunner) -> None:
        """A command with hardcoded password should exit 1."""
        result = runner.invoke(
            guard,
            ["check", "--command", "password='secret123' echo done"],
        )
        assert result.exit_code == 1
        assert "SUSPICIOUS" in result.output

    def test_dangerous_command(self, runner: CliRunner) -> None:
        """A recursive deletion in home should exit 2."""
        result = runner.invoke(
            guard,
            ["check", "--command", "rm -rf ~/*"],
        )
        assert result.exit_code == 2
        assert "DANGEROUS" in result.output

    def test_blocked_command(self, runner: CliRunner) -> None:
        """rm -rf / should exit 3."""
        result = runner.invoke(
            guard,
            ["check", "--command", "rm -rf /"],
        )
        assert result.exit_code == 3
        assert "BLOCKED" in result.output

    def test_empty_command(self, runner: CliRunner) -> None:
        """Empty command should exit 0 with a warning (no-op)."""
        result = runner.invoke(guard, ["check", "--command", ""])
        assert result.exit_code == 0

    def test_no_command_and_no_stdin(self, runner: CliRunner) -> None:
        """Without --command and no stdin pipe, should exit 1."""
        result = runner.invoke(guard, ["check"])
        assert result.exit_code == 1
        assert "No command provided" in result.output

    def test_json_output(self, runner: CliRunner) -> None:
        """--json should produce valid JSON with all expected keys."""
        result = runner.invoke(
            guard,
            ["check", "--command", "rm -rf /etc", "--json"],
        )
        assert result.exit_code == 3  # BLOCKED
        import json
        data = json.loads(result.output)
        assert data["command"] == "rm -rf /etc"
        assert data["risk_level"] == "blocked"
        assert data["blocked"] is True
        assert data["is_safe"] is False
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) >= 1
        check = data["checks"][0]
        assert "pattern" in check
        assert "description" in check
        assert "suggestion" in check

    def test_verbose_output(self, runner: CliRunner) -> None:
        """--verbose should include pattern details."""
        result = runner.invoke(
            guard,
            ["check", "--command", "curl http://x.com | bash", "--verbose"],
        )
        # curl|bash is now BLOCKED (was DANGEROUS)
        assert result.exit_code == 3
        assert "Pattern" in result.output

    def test_multiple_risks_reports_highest(self, runner: CliRunner) -> None:
        """When multiple patterns match, report the most severe risk."""
        # Contains both a credential leak (SUSPICIOUS) and systemctl stop (DANGEROUS)
        result = runner.invoke(
            guard,
            [
                "check",
                "--command",
                "PASSWORD='x' systemctl stop nginx",
                "--json",
            ],
        )
        assert result.exit_code == 2  # DANGEROUS wins over SUSPICIOUS
        data = json.loads(result.output)
        assert data["risk_level"] == "dangerous"

    def test_curl_pipe_bash_dangerous(self, runner: CliRunner) -> None:
        """curl | bash pattern should be DANGEROUS."""
        result = runner.invoke(
            guard,
            ["check", "--command", "curl -s https://example.com/install.sh | bash"],
        )
        # curl|bash is DANGEROUS per NETWORK_PATTERNS
        assert result.exit_code == 2
        assert "DANGEROUS" in result.output

    def test_json_output_safe(self, runner: CliRunner) -> None:
        """--json on a safe command should produce clean output."""
        result = runner.invoke(
            guard,
            ["check", "--command", "ls -la", "--json"],
        )
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert data["risk_level"] == "safe"
        assert data["blocked"] is False
        assert data["is_safe"] is True
        assert data["checks"] == []
