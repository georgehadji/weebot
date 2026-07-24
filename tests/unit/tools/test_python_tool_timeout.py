"""Tests for L15 python timeout clamp."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.tools.python_tool import PythonExecuteTool


class TestTimeoutClamp:
    """L15 — timeout values are clamped to a sensible range."""

    @pytest.fixture
    def tool(self):
        sandbox = AsyncMock()
        sandbox.execute_python = AsyncMock(
            return_value=MagicMock(
                success=True,
                combined_output="ok",
                timed_out=False,
                returncode=0,
                stdout="ok",
                stderr="",
            )
        )
        t = PythonExecuteTool(sandbox=sandbox)
        t._default_timeout = 30.0
        return t

    async def test_timeout_clamped_to_max(self, tool):
        await tool.execute(code="print(1)", timeout=99999)
        call_kwargs = tool._sandbox.execute_python.call_args.kwargs
        assert call_kwargs["timeout"] == 300.0

    async def test_timeout_invalid_string_defaults(self, tool):
        await tool.execute(code="print(1)", timeout="abc")
        call_kwargs = tool._sandbox.execute_python.call_args.kwargs
        assert call_kwargs["timeout"] == 30.0

    async def test_timeout_floor_at_one(self, tool):
        await tool.execute(code="print(1)", timeout=0.1)
        call_kwargs = tool._sandbox.execute_python.call_args.kwargs
        assert call_kwargs["timeout"] == 1.0

    async def test_timeout_within_range_unchanged(self, tool):
        await tool.execute(code="print(1)", timeout=15)
        call_kwargs = tool._sandbox.execute_python.call_args.kwargs
        assert call_kwargs["timeout"] == 15.0
