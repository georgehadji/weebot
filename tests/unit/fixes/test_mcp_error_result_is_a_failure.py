"""An MCP tool result flagged `isError` is a failed call, not a success.

`call_tool` joined the result text and returned it whatever the flag said, so
the tool adapter reported success=True and the executor treated the server's
error message as the tool's output.
"""

from __future__ import annotations

import types

import pytest

from weebot.core.mcp_naming import build_namespaced_name
from weebot.infrastructure.mcp.mcp_client_manager import MCPClientManager
from weebot.infrastructure.mcp.mcp_toolkit_adapter import MCPToolAdapter


class _Session:
    def __init__(self, is_error):
        self._is_error = is_error

    async def call_tool(self, name, arguments):
        return types.SimpleNamespace(
            isError=self._is_error, content=[types.SimpleNamespace(text="boom: bad input")])


def _manager(is_error):
    m = MCPClientManager({})
    m._tools_cache = {"srv": [types.SimpleNamespace(name="do_it")]}
    m._clients = {"srv": _Session(is_error)}
    return m


@pytest.mark.parametrize("is_error, ok", [(True, False), (False, True)])
async def test_the_adapter_reports_the_flag(is_error, ok):
    name = build_namespaced_name("srv", "do_it")
    tool = MCPToolAdapter(name=name, description="", parameters={}, manager=_manager(is_error))
    result = await tool.execute()
    assert result.success is ok
    assert "boom: bad input" in ((result.output or "") + (result.error or ""))
