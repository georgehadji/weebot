"""Unit tests for BashTool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from weebot.sandbox.executor import ExecutionResult
from weebot.tools.bash_tool import BashTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "hello\n") -> ExecutionResult:
    return ExecutionResult(stdout=stdout, stderr="", returncode=0, elapsed_ms=10.0)


def _fail(stderr: str = "something went wrong", returncode: int = 1) -> ExecutionResult:
    return ExecutionResult(stdout="", stderr=stderr, returncode=returncode, elapsed_ms=5.0)


def _timeout() -> ExecutionResult:
    return ExecutionResult(stdout="", stderr="killed", returncode=-1, elapsed_ms=30_000.0, timed_out=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBashTool:

    @pytest.mark.asyncio
    async def test_successful_command_returns_output(self):
        """Happy path: stdout ends up in ToolResult.output."""
        tool = BashTool()
        with patch.object(tool._executor, "run", new=AsyncMock(return_value=_ok("hello\n"))):
            result = await tool.execute(command="echo hello")

        assert not result.is_error
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_denied_command_returns_error(self):
        """A command matching a DENY rule must never reach the executor."""
        tool = BashTool()
        # "format" is a built-in DENY pattern in ExecApprovalPolicy
        run_mock = AsyncMock()
        with patch.object(tool._executor, "run", run_mock):
            result = await tool.execute(command="format c:")

        assert result.is_error
        assert "denied" in result.error.lower()
        run_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_always_ask_command_returns_confirmation_error(self):
        """A command matching an ALWAYS_ASK rule must return an informative error."""
        tool = BashTool()
        # "rm " is a built-in ALWAYS_ASK pattern
        run_mock = AsyncMock()
        with patch.object(tool._executor, "run", run_mock):
            result = await tool.execute(command="rm -rf /tmp/junk")

        assert result.is_error
        assert "confirmation" in result.error.lower()
        run_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_returns_tool_error(self):
        """timed_out=True from executor maps to a clear ToolResult error."""
        tool = BashTool()
        with patch.object(tool._executor, "run", new=AsyncMock(return_value=_timeout())):
            result = await tool.execute(command="sleep 999", timeout=1)

        assert result.is_error
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_is_error(self):
        """Non-zero returncode produces ToolResult with is_error=True."""
        tool = BashTool()
        with patch.object(tool._executor, "run", new=AsyncMock(return_value=_fail())):
            result = await tool.execute(command="false")

        assert result.is_error
        assert "something went wrong" in result.error

    def test_tool_name_and_required_param(self):
        """Metadata contract: name='bash', 'command' is a required property."""
        tool = BashTool()
        assert tool.name == "bash"
        assert "command" in tool.parameters["properties"]
        assert "command" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_executor_called_with_powershell_prefix(self):
        """By default (use_wsl=False) the subprocess uses PowerShell."""
        tool = BashTool()
        captured: list[list[str]] = []

        async def capture_cmd(cmd, **kw):
            captured.append(cmd)
            return _ok()

        with patch.object(tool._executor, "run", side_effect=capture_cmd):
            await tool.execute(command="Get-Date")

        assert captured, "executor.run was not called"
        assert captured[0][0].lower() == "powershell"

    @pytest.mark.asyncio
    async def test_to_param_returns_function_spec(self):
        """to_param() must produce a valid OpenAI function-calling spec."""
        tool = BashTool()
        param = tool.to_param()
        assert param["type"] == "function"
        assert param["function"]["name"] == "bash"
        assert "parameters" in param["function"]
