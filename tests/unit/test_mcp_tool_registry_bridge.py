"""Unit tests for MCPToolRegistryBridge."""
from __future__ import annotations

import asyncio

import pytest

from weebot.application.services.mcp_tool_registry_bridge import (
    MCPToolRegistryBridge,
    _build_namespaced_name,
    _parse_namespaced_name,
    _apply_tool_filters,
)
from weebot.domain.models.mcp import MCPServerConfig, MCPToolInfo, MCPToolFilterConfig
from weebot.tools.tool_registry import RoleBasedToolRegistry


class TestNamespacedNames:
    """Name building and parsing utilities."""

    def test_build_namespaced_name(self):
        assert _build_namespaced_name("stripe", "create_payment") == "mcp__stripe__create_payment"

    def test_build_with_dots_and_hyphens(self):
        assert _build_namespaced_name("my-server.com", "get-data") == "mcp__my_server_com__get_data"

    def test_parse_namespaced_name(self):
        result = _parse_namespaced_name("mcp__stripe__create_payment")
        assert result == ("stripe", "create_payment")

    def test_parse_non_mcp_tool(self):
        assert _parse_namespaced_name("bash") is None

    def test_parse_invalid_format(self):
        assert _parse_namespaced_name("mcp__stripe") is None

    def test_roundtrip(self):
        original = ("my_server", "some_tool")
        namespaced = _build_namespaced_name(*original)
        parsed = _parse_namespaced_name(namespaced)
        assert parsed == original


class TestToolFiltering:
    """Tool filtering by include/exclude patterns."""

    def _make_tool(self, name: str) -> MCPToolInfo:
        return MCPToolInfo(
            original_name=name,
            namespaced_name=f"mcp__server__{name}",
            server_name="server",
        )

    def test_no_filters_passes_all(self):
        config = MCPServerConfig(name="srv", command="npx")
        tools = [self._make_tool("get_weather"), self._make_tool("delete_all")]
        result = _apply_tool_filters(config, tools)
        assert len(result) == 2

    def test_include_filter(self):
        config = MCPServerConfig(
            name="srv", command="npx",
            tools=MCPToolFilterConfig(include=["get_*"]),
        )
        tools = [self._make_tool("get_weather"), self._make_tool("delete_all")]
        result = _apply_tool_filters(config, tools)
        assert len(result) == 1
        assert result[0].original_name == "get_weather"

    def test_exclude_filter(self):
        config = MCPServerConfig(
            name="srv", command="npx",
            tools=MCPToolFilterConfig(exclude=["delete_*"]),
        )
        tools = [self._make_tool("get_weather"), self._make_tool("delete_all")]
        result = _apply_tool_filters(config, tools)
        assert len(result) == 1
        assert result[0].original_name == "get_weather"

    def test_include_and_exclude(self):
        config = MCPServerConfig(
            name="srv", command="npx",
            tools=MCPToolFilterConfig(
                include=["get_*", "list_*", "create_*"],
                exclude=["*_secret", "*_admin"],
            ),
        )
        tools = [
            self._make_tool("get_weather"),
            self._make_tool("get_secret"),
            self._make_tool("create_user"),
            self._make_tool("delete_all"),
        ]
        result = _apply_tool_filters(config, tools)
        names = {t.original_name for t in result}
        assert "get_weather" in names
        assert "get_secret" not in names  # excluded
        assert "create_user" in names
        assert "delete_all" not in names  # not in include

    def test_empty_tools_list(self):
        config = MCPServerConfig(name="srv", command="npx")
        result = _apply_tool_filters(config, [])
        assert result == []


class TestMCPToolRegistryBridge:
    """MCPToolRegistryBridge integration with RoleBasedToolRegistry."""

    @pytest.mark.asyncio
    async def test_bridge_with_no_client(self):
        """Bridge without a client initializes cleanly with 0 tools."""
        registry = RoleBasedToolRegistry()
        bridge = MCPToolRegistryBridge(mcp_client=None, registry=registry)
        count = await bridge.initialize()
        assert count == 0

    @pytest.mark.asyncio
    async def test_bridge_close_without_client(self):
        """Close without a client should not crash."""
        bridge = MCPToolRegistryBridge()
        await bridge.close()  # Should not raise

    def test_get_stats_empty(self):
        bridge = MCPToolRegistryBridge()
        stats = bridge.get_stats()
        assert stats["servers"] == 0
        assert stats["total_tools"] == 0

    def test_get_registered_tools_empty(self):
        bridge = MCPToolRegistryBridge()
        assert bridge.get_registered_tools() == {}

    def test_register_single_tool(self):
        """Verify that _register_single_tool adds to admin/automation roles."""
        registry = RoleBasedToolRegistry()
        bridge = MCPToolRegistryBridge(mcp_client=None, registry=registry)

        tool_info = MCPToolInfo(
            original_name="get_weather",
            namespaced_name="mcp__weather__get_weather",
            server_name="weather",
        )
        bridge._register_single_tool("weather", tool_info)

        # The tool should be in admin, automation, researcher, coder roles
        assert registry.validate_tool_for_role("admin", "mcp__weather__get_weather")
        assert registry.validate_tool_for_role("automation", "mcp__weather__get_weather")

    @pytest.mark.asyncio
    async def test_register_followed_by_unregister(self):
        """Registering then unregistering a server removes all its tools."""
        registry = RoleBasedToolRegistry()
        bridge = MCPToolRegistryBridge(mcp_client=None, registry=registry)

        tool_info = MCPToolInfo(
            original_name="get_weather",
            namespaced_name="mcp__weather__get_weather",
            server_name="weather",
        )
        bridge._register_single_tool("weather", tool_info)
        bridge._registered_tools["weather"] = ["mcp__weather__get_weather"]

        assert registry.validate_tool_for_role("admin", "mcp__weather__get_weather")

        # Now unregister
        count = await bridge.unregister_server_tools("weather")
        assert count == 1
        assert not registry.validate_tool_for_role("admin", "mcp__weather__get_weather")

    @pytest.mark.asyncio
    async def test_unregister_unknown_server(self):
        """Unregistering a non-existent server returns 0."""
        bridge = MCPToolRegistryBridge()
        count = await bridge.unregister_server_tools("nonexistent")
        assert count == 0
