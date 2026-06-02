"""Regression test: MCPClientManager.initialize() silent failure bug.

BUG: _connect_with_retry() logged errors but never raised on final failure.
initialize() set _initialized = True even when ALL servers failed to connect.
Subsequent call_tool() calls failed with confusing error messages instead of
a clear "server not connected" error.

FIX: _connect_with_retry() now raises RuntimeError after exhausting retries.
initialize() raises RuntimeError when all enabled servers fail.
"""
from __future__ import annotations

import pytest

from weebot.infrastructure.mcp.mcp_client_manager import MCPClientManager


@pytest.mark.asyncio
async def test_initialize_raises_when_all_servers_fail():
    """initialize() must raise RuntimeError when every server fails to connect."""
    mgr = MCPClientManager(
        config={
            "mcpServers": {
                "bad1": {
                    "enabled": True,
                    "transport": "stdio",
                    "command": "/nonexistent/binary_xyz_123",
                    "args": [],
                },
                "bad2": {
                    "enabled": True,
                    "transport": "sse",
                    "url": "http://127.0.0.1:19999/nonexistent",
                },
            }
        },
        max_retries=1,
    )

    with pytest.raises(RuntimeError, match="All MCP servers failed"):
        await mgr.initialize()


@pytest.mark.asyncio
async def test_initialize_succeeds_when_at_least_one_server_connects(monkeypatch):
    """initialize() should not raise if at least one server succeeds, even
    if others fail."""
    mgr = MCPClientManager(
        config={
            "mcpServers": {
                "good": {
                    "enabled": True,
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-c", "print('ok')"],
                },
                "bad": {
                    "enabled": True,
                    "transport": "stdio",
                    "command": "/nonexistent/binary_xyz_456",
                    "args": [],
                },
            }
        },
        max_retries=1,
    )

    # Patch _connect_server for "good" so we don't actually need a real
    # MCP server — just simulate a successful connection.
    original_connect = mgr._connect_server

    async def fake_connect(name, cfg):
        if name == "good":
            # Simulate success: create a minimal fake session
            class FakeSession:
                async def initialize(self): pass
                async def list_tools(self):
                    class FakeTools:
                        tools = []
                    return FakeTools()
            mgr._clients[name] = FakeSession()
            mgr._tools_cache[name] = []
            return
        # Let "bad" fail normally
        await original_connect(name, cfg)

    monkeypatch.setattr(mgr, "_connect_server", fake_connect)

    # Should not raise — "good" succeeded
    await mgr.initialize()
    assert "good" in mgr._clients


@pytest.mark.asyncio
async def test_retry_exhaustion_raises():
    """After max_retries attempts, _connect_with_retry must raise."""
    mgr = MCPClientManager(
        config={"mcpServers": {}},
        max_retries=2,
    )

    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        await mgr._connect_with_retry(
            "doomed",
            {
                "transport": "stdio",
                "command": "/definitely/does/not/exist",
                "args": [],
            },
        )
