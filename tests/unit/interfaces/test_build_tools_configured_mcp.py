"""build_tools() brings in the MCP servers configured in MCP_SERVERS_CONFIG_PATH.

Found while connecting Postiz: the configured servers never reached a flow.
MCPToolRegistryBridge only adds tool *names* to roles, the registry builds
tools from its class map (which has no MCP entries) and skips the rest, and
build_tools() only loaded MCP tools when a caller passed mcp_config, which no
caller does. Now build_tools() connects the DI "mcp_client" once per process
and adds its tools before the guard wrap, so outbound ones (Postiz
schedulePostTool) are GuardedTool and all of them are untrusted output.
"""

from __future__ import annotations

import logging

import pytest

from weebot.application.services.tool_guards import GuardedTool
from weebot.core.trust_boundary import is_untrusted_tool
from weebot.interfaces import factories


class _FakeManager:
    has_servers = True

    def __init__(self):
        self.initialized = 0

    async def initialize(self):
        self.initialized += 1

    async def get_all_tools(self):
        def spec(name):
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"[postiz] {name}",
                    "parameters": {"type": "object", "properties": {}},
                },
            }

        return [spec("mcp__postiz__schedulePostTool"), spec("mcp__postiz__postsListTool")]

    async def call_tool(self, name, args):
        return f"called {name}"


@pytest.fixture
def manager(monkeypatch):
    fake = _FakeManager()
    monkeypatch.setattr(factories, "_resolve_mcp_client", lambda: fake)
    monkeypatch.setattr(factories, "_MCP_TOOLKIT", None)
    return fake


async def test_configured_mcp_tools_join_the_collection_guarded(manager):
    tools = await factories.build_tools(role="researcher")
    post = tools.get_tool("mcp__postiz__schedulePostTool")
    listing = tools.get_tool("mcp__postiz__postsListTool")
    assert isinstance(post, GuardedTool)
    assert listing is not None and not isinstance(listing, GuardedTool)
    assert is_untrusted_tool("mcp__postiz__postsListTool")
    assert (await listing.execute()).output == "called mcp__postiz__postsListTool"


async def test_servers_connect_once_per_process(manager):
    await factories.build_tools(role="researcher")
    await factories.build_tools(role="admin")
    assert manager.initialized == 1


async def test_no_configured_servers_adds_nothing(monkeypatch):
    class _Empty(_FakeManager):
        has_servers = False

    empty = _Empty()
    monkeypatch.setattr(factories, "_resolve_mcp_client", lambda: empty)
    monkeypatch.setattr(factories, "_MCP_TOOLKIT", None)
    tools = await factories.build_tools(role="researcher")
    assert not [t for t in tools if t.name.startswith("mcp__")]
    assert empty.initialized == 0


async def test_a_server_that_fails_to_connect_is_skipped_with_a_warning(monkeypatch, caplog):
    class _Down(_FakeManager):
        async def initialize(self):
            raise RuntimeError("All MCP servers failed to connect: postiz")

    monkeypatch.setattr(factories, "_resolve_mcp_client", lambda: _Down())
    monkeypatch.setattr(factories, "_MCP_TOOLKIT", None)
    with caplog.at_level(logging.WARNING):
        tools = await factories.build_tools(role="researcher")
    assert tools.get_tool("web_search") is not None
    assert "postiz" in caplog.text
