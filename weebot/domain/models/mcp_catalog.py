"""MCP tool catalog models for scoped (per-request) tool retrieval."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MCPToolCatalogIndex(BaseModel):
    """An indexed MCP tool ready for semantic retrieval."""

    original_name: str = Field(description="Tool name as returned by the MCP server")
    namespaced_name: str = Field(description="Namespaced name: mcp__<server>__<tool>")
    description: str = Field(default="", description="Tool description from the server")
    server_name: str = Field(description="Originating server name")
    embedding: list[float] | None = Field(
        default=None, description="Vector embedding of description"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
