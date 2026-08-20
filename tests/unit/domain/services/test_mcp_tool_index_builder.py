"""Unit tests for the MCP tool catalog index builder."""

from __future__ import annotations

import pytest

from weebot.domain.models.mcp import MCPToolInfo
from weebot.domain.services.mcp_tool_index_builder import build_index


class TestBuildIndex:
    """Pure-function builder for the searchable MCP tool catalog."""

    @staticmethod
    def _make_tool(name: str, description: str) -> MCPToolInfo:
        return MCPToolInfo(
            original_name=name,
            namespaced_name=f"mcp__srv__{name}",
            description=description,
            input_schema={"type": "object"},
            server_name="srv",
        )

    def test_build_index_without_embeddings(self):
        tools = [
            self._make_tool("get_weather", "Get weather"),
            self._make_tool("send_email", "Send email"),
        ]
        index = build_index(tools)

        assert len(index) == 2
        assert index[0].original_name == "get_weather"
        assert index[0].embedding is None
        assert index[0].metadata["input_schema"] == {"type": "object"}

    def test_build_index_with_embeddings(self):
        tools = [
            self._make_tool("get_weather", "Get weather"),
            self._make_tool("send_email", "Send email"),
        ]
        embeddings = [[0.1, 0.2], [0.3, 0.4]]
        index = build_index(tools, embeddings=embeddings)

        assert index[0].embedding == [0.1, 0.2]
        assert index[1].embedding == [0.3, 0.4]

    def test_build_index_empty(self):
        assert build_index([]) == []

    def test_build_index_length_mismatch_raises(self):
        tools = [self._make_tool("a", "desc")]
        with pytest.raises(ValueError):
            build_index(tools, embeddings=[[0.1], [0.2]])

    def test_build_index_preserves_order(self):
        tools = [self._make_tool("z", "last"), self._make_tool("a", "first")]
        index = build_index(tools)

        assert [i.original_name for i in index] == ["z", "a"]
