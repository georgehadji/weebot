"""Unit tests for MCP catalog domain models."""

from __future__ import annotations

from weebot.domain.models.mcp_catalog import MCPToolCatalogIndex


class TestMCPToolCatalogIndex:
    """Serialization and field behavior for MCPToolCatalogIndex."""

    def test_catalog_index_serializes(self):
        index = MCPToolCatalogIndex(
            original_name="get_weather",
            namespaced_name="mcp__server__get_weather",
            description="Fetch weather for a location",
            server_name="server",
            embedding=[0.1, 0.2, 0.3],
            metadata={"input_schema": {"type": "object"}},
        )
        data = index.model_dump()
        assert data["original_name"] == "get_weather"
        assert data["namespaced_name"] == "mcp__server__get_weather"
        assert data["description"] == "Fetch weather for a location"
        assert data["server_name"] == "server"
        assert data["embedding"] == [0.1, 0.2, 0.3]
        assert data["metadata"] == {"input_schema": {"type": "object"}}

    def test_catalog_index_roundtrip(self):
        original = MCPToolCatalogIndex(
            original_name="create_user",
            namespaced_name="mcp__auth__create_user",
            description="Create a user",
            server_name="auth",
        )
        restored = MCPToolCatalogIndex(**original.model_dump())
        assert restored == original

    def test_default_embedding_is_none(self):
        index = MCPToolCatalogIndex(
            original_name="ping",
            namespaced_name="mcp__server__ping",
            description="Health check",
            server_name="server",
        )
        assert index.embedding is None

    def test_default_metadata_is_empty(self):
        index = MCPToolCatalogIndex(
            original_name="ping",
            namespaced_name="mcp__server__ping",
            description="Health check",
            server_name="server",
        )
        assert index.metadata == {}
