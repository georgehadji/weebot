"""A config handed to MCPToolkitAdapter.initialize gets `${VAR}` expanded.

The DI path expanded variables; this one passed `${APIFY_API_KEY}` to the
server literally, as the bearer token.
"""

from __future__ import annotations

from weebot.infrastructure.mcp import mcp_toolkit_adapter as mta


async def test_variables_are_expanded(monkeypatch):
    monkeypatch.setenv("WB_TEST_TOKEN", "tok")

    async def _noop(self):
        return None

    async def _none(self):
        return []

    monkeypatch.setattr(mta.MCPClientManager, "initialize", _noop)
    monkeypatch.setattr(mta.MCPClientManager, "get_all_tools", _none)
    adapter = mta.MCPToolkitAdapter()
    headers = {"Authorization": "Bearer ${WB_TEST_TOKEN}"}
    await adapter.initialize({"mcpServers": {"s": {"headers": headers}}})
    assert adapter._manager._config["mcpServers"]["s"]["headers"]["Authorization"] == "Bearer tok"
