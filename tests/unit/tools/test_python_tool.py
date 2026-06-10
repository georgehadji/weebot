"""Unit tests for PythonExecuteTool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from weebot.application.ports.sandbox_port import SandboxResult
from weebot.tools.python_tool import PythonExecuteTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "42\n") -> SandboxResult:
    return SandboxResult(stdout=stdout, stderr="", returncode=0, elapsed_ms=50.0)


def _fail(stderr: str = "Traceback...", returncode: int = 1) -> SandboxResult:
    return SandboxResult(stdout="", stderr=stderr, returncode=returncode, elapsed_ms=20.0)


def _timeout() -> SandboxResult:
    return SandboxResult(
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
        with patch.object(tool._sandbox, "execute_python", new=AsyncMock(return_value=_ok("hello\n"))):
            result = await tool.execute(code='print("hello")')

        assert not result.is_error
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_syntax_error_captured_as_tool_error(self):
        """Syntax / runtime errors in stderr produce is_error=True."""
        tool = PythonExecuteTool()
        err = "SyntaxError: invalid syntax"
        with patch.object(tool._sandbox, "execute_python", new=AsyncMock(return_value=_fail(err))):
            result = await tool.execute(code="!!!bad code!!!")

        assert result.is_error
        assert "SyntaxError" in result.error

    @pytest.mark.asyncio
    async def test_runtime_error_captured_as_tool_error(self):
        """ZeroDivisionError or other runtime exceptions map to ToolResult.error."""
        tool = PythonExecuteTool()
        err = "ZeroDivisionError: division by zero"
        with patch.object(tool._sandbox, "execute_python", new=AsyncMock(return_value=_fail(err))):
            result = await tool.execute(code="1/0")

        assert result.is_error
        assert "ZeroDivisionError" in result.error

    @pytest.mark.asyncio
    async def test_timeout_returns_tool_error(self):
        """timed_out=True from executor produces a clear timeout message."""
        tool = PythonExecuteTool()
        with patch.object(tool._sandbox, "execute_python", new=AsyncMock(return_value=_timeout())):
            result = await tool.execute(code="import time; time.sleep(9999)", timeout=1)

        assert result.is_error
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_denied_code_returns_error_without_running(self):
        """Code matching a DENY policy rule must not reach the executor."""
        # Note: blanket "format" was removed from DENY rules (false-positive source).
        # The remaining DENY patterns target disk format commands. Use "Format-Volume"
        # which matches ExecApprovalPolicy's \bFormat-Volume\b DENY regex but does NOT
        # match BashGuard's \bformat\s+[a-zA-Z]: (since -Volume follows "format").
        tool = PythonExecuteTool()
        run_mock = AsyncMock()
        with patch.object(tool._sandbox, "execute_python", run_mock):
            # Format-Volume matches the DENY regex in ExecApprovalPolicy
            result = await tool.execute(code="Format-Volume D: -FileSystem NTFS")

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
        # Note: execute_python() receives keyword arguments (code=, timeout=, memory_limit_mb=),
        # NOT a positional "cmd" argument. The mock must match the actual method signature.
        tool = PythonExecuteTool()
        captured_code: str | None = None

        async def capture_execute_python(code="", timeout=None, memory_limit_mb=None, **kw):
            nonlocal captured_code
            captured_code = code
            return _ok()

        with patch.object(tool._sandbox, "execute_python", side_effect=capture_execute_python):
            await tool.execute(code='print("x")')

        assert captured_code is not None, "execute_python was not called"
        assert "print" in captured_code

    @pytest.mark.asyncio
    async def test_to_param_returns_function_spec(self):
        """to_param() must produce a valid OpenAI function-calling spec."""
        tool = PythonExecuteTool()
        param = tool.to_param()
        assert param["type"] == "function"
        assert param["function"]["name"] == "python_execute"
        assert "parameters" in param["function"]


# ---------------------------------------------------------------------------
# Fix 7: _contextual_hint
# ---------------------------------------------------------------------------

class TestContextualHint:
    """Tests for Fix 7: contextual undo_hint based on code."""

    def test_contextual_hint_for_sys(self):
        from weebot.tools.python_tool import _contextual_hint
        hint = _contextual_hint("import sys\nprint(sys.argv)", "base hint")
        assert "sys module" in hint

    def test_contextual_hint_for_file_write(self):
        from weebot.tools.python_tool import _contextual_hint
        hint = _contextual_hint("with open('file.txt', 'w') as f: f.write('hello')", "base hint")
        assert "opens files" in hint

    def test_contextual_hint_for_delete(self):
        from weebot.tools.python_tool import _contextual_hint
        hint = _contextual_hint("os.remove('/tmp/test')", "base hint")
        assert "delete files" in hint

    def test_contextual_hint_passthrough(self):
        from weebot.tools.python_tool import _contextual_hint
        hint = _contextual_hint("x = 1 + 1", "base hint")
        assert hint == "base hint"

    def test_contextual_hint_for_rmtree(self):
        from weebot.tools.python_tool import _contextual_hint
        hint = _contextual_hint("shutil.rmtree('/tmp/build')", "base hint")
        assert "delete files" in hint
