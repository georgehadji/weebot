"""Unit tests for PythonExecuteTool."""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest

from weebot.sandbox.executor import ExecutionResult
from weebot.tools.python_tool import PythonExecuteTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "42\n") -> ExecutionResult:
    return ExecutionResult(stdout=stdout, stderr="", returncode=0, elapsed_ms=50.0)


def _fail(stderr: str = "Traceback...", returncode: int = 1) -> ExecutionResult:
    return ExecutionResult(stdout="", stderr=stderr, returncode=returncode, elapsed_ms=20.0)


def _timeout() -> ExecutionResult:
    return ExecutionResult(
        stdout="", stderr="killed", returncode=-1, elapsed_ms=30_000.0, timed_out=True
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPythonExecuteTool:

    @pytest.mark.asyncio
    async def test_successful_code_returns_stdout(self):
        """Happy path: print() output captured in ToolResult.output."""
        tool = PythonExecuteTool()
        with patch.object(tool._executor, "run", new=AsyncMock(return_value=_ok("hello\n"))):
            result = await tool.execute(code='print("hello")')

        assert not result.is_error
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_syntax_error_captured_as_tool_error(self):
        """Syntax / runtime errors in stderr produce is_error=True."""
        tool = PythonExecuteTool()
        err = "SyntaxError: invalid syntax"
        with patch.object(tool._executor, "run", new=AsyncMock(return_value=_fail(err))):
            result = await tool.execute(code="!!!bad code!!!")

        assert result.is_error
        assert "SyntaxError" in result.error

    @pytest.mark.asyncio
    async def test_runtime_error_captured_as_tool_error(self):
        """ZeroDivisionError or other runtime exceptions map to ToolResult.error."""
        tool = PythonExecuteTool()
        err = "ZeroDivisionError: division by zero"
        with patch.object(tool._executor, "run", new=AsyncMock(return_value=_fail(err))):
            result = await tool.execute(code="1/0")

        assert result.is_error
        assert "ZeroDivisionError" in result.error

    @pytest.mark.asyncio
    async def test_timeout_returns_tool_error(self):
        """timed_out=True from executor produces a clear timeout message."""
        tool = PythonExecuteTool()
        with patch.object(tool._executor, "run", new=AsyncMock(return_value=_timeout())):
            result = await tool.execute(code="import time; time.sleep(9999)", timeout=1)

        assert result.is_error
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_denied_code_returns_error_without_running(self):
        """Code matching a DENY policy rule must not reach the executor."""
        tool = PythonExecuteTool()
        run_mock = AsyncMock()
        with patch.object(tool._executor, "run", run_mock):
            # "format" is a built-in DENY pattern in ExecApprovalPolicy
            result = await tool.execute(code="format(42)")

        assert result.is_error
        assert "denied" in result.error.lower()
        run_mock.assert_not_called()

    def test_tool_name_and_required_param(self):
        """Metadata contract: name='python_execute', 'code' is required."""
        tool = PythonExecuteTool()
        assert tool.name == "python_execute"
        assert "code" in tool.parameters["properties"]
        assert "code" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_executor_invoked_with_python_executable(self):
        """subprocess cmd must start with sys.executable and -c flag."""
        tool = PythonExecuteTool()
        captured: list[list[str]] = []

        async def capture_cmd(cmd, **kw):
            captured.append(cmd)
            return _ok()

        with patch.object(tool._executor, "run", side_effect=capture_cmd):
            await tool.execute(code='print("x")')

        assert captured, "executor.run was not called"
        assert captured[0][0] == sys.executable
        assert captured[0][1] == "-c"
        assert captured[0][2] == 'print("x")'

    @pytest.mark.asyncio
    async def test_to_param_returns_function_spec(self):
        """to_param() must produce a valid OpenAI function-calling spec."""
        tool = PythonExecuteTool()
        param = tool.to_param()
        assert param["type"] == "function"
        assert param["function"]["name"] == "python_execute"
        assert "parameters" in param["function"]
