"""Unit tests for Subagent RPC (Hermes M8).

Covers:
- SubagentRPCTool.execute() with simple scripts
- Script timeout handling
- JSON output parsing
"""
import pytest


class TestSubagentRPCTool:
    """Validates SubagentRPCTool."""

    @pytest.mark.asyncio
    async def test_simple_script(self):
        """A simple print script returns its output."""
        from weebot.tools.subagent_rpc import SubagentRPCTool

        tool = SubagentRPCTool()
        result = await tool.execute("print('hello from subagent')")

        assert result.success
        assert "hello from subagent" in result.output

    @pytest.mark.asyncio
    async def test_multi_line_output(self):
        """Multi-line output is preserved."""
        from weebot.tools.subagent_rpc import SubagentRPCTool

        tool = SubagentRPCTool()
        result = await tool.execute(
            "for i in range(3):\n    print(f'line {i}')"
        )

        assert result.success
        assert "line 0" in result.output
        assert "line 1" in result.output
        assert "line 2" in result.output

    @pytest.mark.asyncio
    async def test_script_with_error(self):
        """Syntax errors are captured in stderr."""
        from weebot.tools.subagent_rpc import SubagentRPCTool

        tool = SubagentRPCTool()
        result = await tool.execute("invalid python code {{{")

        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Script exceeding timeout returns an error."""
        from weebot.tools.subagent_rpc import SubagentRPCTool

        tool = SubagentRPCTool()
        result = await tool.execute(
            "import time; time.sleep(10)",
            timeout=0.5,
        )

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rpc_call_script(self):
        """Script using rpc_call generates structured output."""
        from weebot.tools.subagent_rpc import SubagentRPCTool

        tool = SubagentRPCTool()
        result = await tool.execute(
            "result = rpc_call('bash', command='echo hello')\nprint(result)"
        )

        assert result.success
        assert "RPC" in result.output or "bash" in result.output

    @pytest.mark.asyncio
    async def test_computation_script(self):
        """Script computing a value returns the result."""
        from weebot.tools.subagent_rpc import SubagentRPCTool

        tool = SubagentRPCTool()
        result = await tool.execute(
            "data = [i * 2 for i in range(1000)]\n"
            "print(f'Computed {len(data)} values, sum: {sum(data)}')"
        )

        assert result.success
        assert "Computed 1000" in result.output
