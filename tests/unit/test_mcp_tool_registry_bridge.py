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
from weebot.application.services.mcp_tool_retrieval_service import (
    McpToolRetrievalService,
)
from weebot.domain.models.mcp import MCPServerConfig, MCPToolInfo, MCPToolFilterConfig
from weebot.tools.tool_registry import RoleBasedToolRegistry


class _FakeRetrievalPort:
    """Minimal retrieval port for bridge tests."""

    def __init__(self, tools) -> None:
        self._tools = list(tools)
        self.indexed = []

    async def index_tools(self, tools) -> None:
        self.indexed = list(tools)

    async def retrieve_for_query(self, query: str, k: int = 8):
        if not query:
            return []
        return [t for t in self._tools if query.lower() in t.description.lower()][:k]


class _FakeRegistrationPort:
    """Minimal registration port for bridge tests."""

    def __init__(self, roles=None) -> None:
        self._roles = {role: [] for role in (roles or [])}

    def add_tool_to_role(self, role: str, tool_name: str) -> None:
        if role not in self._roles:
            self._roles[role] = []
        if tool_name not in self._roles[role]:
            self._roles[role].append(tool_name)

    def remove_tool_from_role(self, role: str, tool_name: str) -> None:
        if role in self._roles and tool_name in self._roles[role]:
            self._roles[role].remove(tool_name)

    def list_roles(self):
        return list(self._roles.keys())


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


class TestMCPToolRegistryBridgeRetrieval:
    """H1: scoped retrieval integration with MCPToolRegistryBridge."""

    @staticmethod
    def _make_tool(name: str, description: str) -> MCPToolInfo:
        return MCPToolInfo(
            original_name=name,
            namespaced_name=f"mcp__srv__{name}",
            description=description,
            input_schema={},
            server_name="srv",
        )

    @pytest.mark.asyncio
    async def test_scope_for_query_without_service_returns_all_tools(self):
        registry = RoleBasedToolRegistry()
        bridge = MCPToolRegistryBridge(mcp_client=None, registry=registry)
        bridge._registered_tools["srv"] = ["mcp__srv__a", "mcp__srv__b"]

        with pytest.warns(DeprecationWarning, match="scope_for_query"):
            result = await bridge.scope_for_query("anything")

        assert sorted(result) == ["mcp__srv__a", "mcp__srv__b"]

    @pytest.mark.asyncio
    async def test_scope_for_query_with_service_returns_namespaced_names(self):
        tools = [
            self._make_tool("get_weather", "Get weather"),
            self._make_tool("send_email", "Send email"),
        ]
        retrieval_port = _FakeRetrievalPort(tools)
        registration_port = _FakeRegistrationPort(roles=["admin"])
        service = McpToolRetrievalService(
            retrieval_port=retrieval_port,
            registration_port=registration_port,
            k=8,
        )

        registry = RoleBasedToolRegistry()
        bridge = MCPToolRegistryBridge(mcp_client=None, registry=registry)
        bridge.set_retrieval_service(service)
        bridge._registered_tool_infos["srv"] = tools

        with pytest.warns(DeprecationWarning, match="scope_for_query"):
            result = await bridge.scope_for_query("weather")

        assert result == ["mcp__srv__get_weather"]

    @pytest.mark.asyncio
    async def test_initialize_indexes_tools_when_service_wired(self):
        tools = [
            self._make_tool("get_weather", "Get weather"),
        ]

        class _FakeClient:
            async def get_all_tools(self):
                return [
                    {
                        "name": "mcp__srv__get_weather",
                        "description": "Get weather",
                    }
                ]

        retrieval_port = _FakeRetrievalPort(tools)
        registration_port = _FakeRegistrationPort(roles=["admin"])
        service = McpToolRetrievalService(
            retrieval_port=retrieval_port,
            registration_port=registration_port,
            k=8,
        )

        registry = RoleBasedToolRegistry()
        bridge = MCPToolRegistryBridge(mcp_client=_FakeClient(), registry=registry)
        bridge.set_server_configs({"srv": MCPServerConfig(name="srv", command="npx")})
        bridge.set_retrieval_service(service)

        count = await bridge.initialize()

        assert count == 1
        assert len(retrieval_port.indexed) == 1
        assert retrieval_port.indexed[0].original_name == "get_weather"
