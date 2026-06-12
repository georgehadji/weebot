"""Phase 7 tests: CLI harness evolve command + integration smoke test."""
from __future__ import annotations

from click.testing import CliRunner
import pytest


class TestHarnessEvolveCli:
    """Test that the harness evolve CLI command is registered and parses args."""

    def test_evolve_command_registered(self):
        """Verify 'harness evolve' appears in help output."""
        from cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["harness", "--help"])
        assert result.exit_code == 0
        assert "evolve" in result.output

    def test_evolve_help(self):
        """Verify 'harness evolve --help' shows expected options."""
        from cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["harness", "evolve", "--help"])
        assert result.exit_code == 0
        assert "--harness-path" in result.output
        assert "--held-in-tasks" in result.output
        assert "--max-proposals" in result.output
        assert "--iterations" in result.output

    def test_evolve_options_parsed(self):
        """Verify all evolve options parse without errors."""
        from cli.main import cli

        runner = CliRunner()
        # Pass valid options but let it fail on DI (no API keys in test env).
        # We're testing option parsing, not the async flow.
        result = runner.invoke(cli, [
            "harness", "evolve",
            "--iterations", "1",
            "--max-proposals", "2",
            "--harness-path", "weebot/config/harness/v0.2.0.yaml",
            "--db", ":memory:",
        ])
        # Exit code 0 = clean run, 1 = runtime error (no LLM configured).
        # Exit code 2 = Click argument parse error — that's a real bug.
        assert result.exit_code != 2, (
            f"CLI argument parsing failed:\n{result.output}"
        )


class TestJobsYaml:
    def test_self_harness_job_registered(self):
        """Verify the self-harness weekly cron job is in jobs.yaml."""
        import yaml
        from pathlib import Path

        jobs_path = Path("weebot/config/jobs.yaml")
        assert jobs_path.exists()

        data = yaml.safe_load(jobs_path.read_text(encoding="utf-8"))
        job_ids = [j["job_id"] for j in data.get("jobs", [])]
        assert "self_harness_weekly" in job_ids
