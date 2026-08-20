"""Unit tests for McpToolRetrievalService."""

from __future__ import annotations


import pytest

from weebot.application.ports.mcp_tool_registration_port import McpToolRegistrationPort
from weebot.application.ports.mcp_tool_retrieval_port import McpToolRetrievalPort
from weebot.application.services.mcp_tool_retrieval_service import McpToolRetrievalService
from weebot.domain.models.mcp import MCPToolInfo


class _FakeRetrievalPort(McpToolRetrievalPort):
    """In-memory retrieval port for testing."""

    def __init__(self, tools: list[MCPToolInfo]) -> None:
        self._tools = list(tools)
        self.indexed: list[MCPToolInfo] = []

    async def index_tools(self, tools: list[MCPToolInfo]) -> None:
        self.indexed = list(tools)

    async def retrieve_for_query(self, query: str, k: int = 8) -> list[MCPToolInfo]:
        # Simple deterministic stub: return first k tools whose description
        # contains the query substring (case-insensitive).  Empty query returns
        # nothing so the service degrades gracefully.
        if not query:
            return []
        query_lower = query.lower()
        matches = [t for t in self._tools if query_lower in t.description.lower()]
        return matches[:k]


class _FakeRegistrationPort(McpToolRegistrationPort):
    """In-memory registration port capturing role mutations."""

    def __init__(self, roles: list[str] | None = None) -> None:
        self._roles: dict[str, list[str]] = {role: [] for role in (roles or [])}

    def add_tool_to_role(self, role: str, tool_name: str) -> None:
        if role not in self._roles:
            self._roles[role] = []
        if tool_name not in self._roles[role]:
            self._roles[role].append(tool_name)

    def remove_tool_from_role(self, role: str, tool_name: str) -> None:
        if role in self._roles and tool_name in self._roles[role]:
            self._roles[role].remove(tool_name)

    def list_roles(self) -> list[str]:
        return list(self._roles.keys())

    def tools_in_role(self, role: str) -> list[str]:
        return list(self._roles.get(role, []))


class TestMcpToolRetrievalService:
    """Scoped retrieval orchestration."""

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
    async def test_index_all_tools_passes_tools_to_retrieval_port(self):
        tools = [
            self._make_tool("get_weather", "Get weather"),
            self._make_tool("send_email", "Send email"),
        ]
        retrieval = _FakeRetrievalPort(tools)
        registration = _FakeRegistrationPort()
        service = McpToolRetrievalService(retrieval, registration, k=2)

        await service.index_all_tools(tools)

        assert retrieval.indexed == tools

    @pytest.mark.asyncio
    async def test_scope_for_query_returns_relevant_tools(self):
        tools = [
            self._make_tool("get_weather", "Get weather for a city"),
            self._make_tool("send_email", "Send an email message"),
            self._make_tool("search_web", "Search the web"),
        ]
        retrieval = _FakeRetrievalPort(tools)
        registration = _FakeRegistrationPort(roles=["admin", "coder"])
        service = McpToolRetrievalService(retrieval, registration, k=8)
        await service.index_all_tools(tools)

        relevant = await service.scope_for_query("weather")

        assert len(relevant) == 1
        assert relevant[0].original_name == "get_weather"

    @pytest.mark.asyncio
    async def test_scope_for_query_clears_previous_scope(self):
        tools = [
            self._make_tool("get_weather", "Get weather for a city"),
            self._make_tool("send_email", "Send an email message"),
        ]
        retrieval = _FakeRetrievalPort(tools)
        registration = _FakeRegistrationPort(roles=["admin"])
        service = McpToolRetrievalService(retrieval, registration, k=8)
        await service.index_all_tools(tools)

        await service.scope_for_query("weather")
        assert registration.tools_in_role("admin") == ["mcp__srv__get_weather"]

        await service.scope_for_query("email")
        assert registration.tools_in_role("admin") == ["mcp__srv__send_email"]

    @pytest.mark.asyncio
    async def test_scope_for_query_adds_relevant_tools_to_all_roles(self):
        tools = [self._make_tool("get_weather", "Get weather for a city")]
        retrieval = _FakeRetrievalPort(tools)
        registration = _FakeRegistrationPort(roles=["admin", "coder"])
        service = McpToolRetrievalService(retrieval, registration, k=8)
        await service.index_all_tools(tools)

        await service.scope_for_query("weather")

        assert "mcp__srv__get_weather" in registration.tools_in_role("admin")
        assert "mcp__srv__get_weather" in registration.tools_in_role("coder")

    @pytest.mark.asyncio
    async def test_scope_for_query_empty_query_returns_empty(self):
        tools = [self._make_tool("get_weather", "Get weather")]
        retrieval = _FakeRetrievalPort(tools)
        registration = _FakeRegistrationPort(roles=["admin"])
        service = McpToolRetrievalService(retrieval, registration, k=8)
        await service.index_all_tools(tools)

        relevant = await service.scope_for_query("")

        assert relevant == []
        assert registration.tools_in_role("admin") == []

    @pytest.mark.asyncio
    async def test_scope_for_query_respects_k(self):
        tools = [
            self._make_tool("a", "weather alpha"),
            self._make_tool("b", "weather beta"),
            self._make_tool("c", "weather gamma"),
        ]
        retrieval = _FakeRetrievalPort(tools)
        registration = _FakeRegistrationPort(roles=["admin"])
        service = McpToolRetrievalService(retrieval, registration, k=2)
        await service.index_all_tools(tools)

        relevant = await service.scope_for_query("weather")

        assert len(relevant) == 2

    @pytest.mark.asyncio
    async def test_scope_for_query_no_roles_is_noop(self):
        tools = [self._make_tool("get_weather", "Get weather")]
        retrieval = _FakeRetrievalPort(tools)
        registration = _FakeRegistrationPort(roles=[])
        service = McpToolRetrievalService(retrieval, registration, k=8)
        await service.index_all_tools(tools)

        relevant = await service.scope_for_query("weather")

        # Retrieval still returns matches even when no roles exist.
        assert len(relevant) == 1
