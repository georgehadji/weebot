"""ToolManifest — domain model describing a tool available for discovery.

Used by :class:`~weebot.application.ports.tool_discovery_port.ToolDiscoveryPort`
to expose the tool catalog to MCP clients, CLI, and web UI.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ToolManifest(BaseModel):
    """Metadata for a discoverable agent tool.

    Each ``BaseTool`` subclass can declare these fields as class-level
    attributes so the discovery adapter can build manifests without
    instantiating the tool.
    """

    name: str = Field(
        description="Unique tool name matching BaseTool.name (e.g. 'bash', 'web_search').",
        min_length=1,
    )
    description: str = Field(
        default="",
        description="Human-readable description of what the tool does.",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Roles that have access to this tool (empty = all roles).",
    )
    requires_deps: list[str] = Field(
        default_factory=list,
        description="Optional Python packages required (e.g. ['playwright', 'browser_use']).",
    )
    mcp_safe: bool = Field(
        default=False,
        description="Whether this tool can be exposed via MCP without confirmation.",
    )
    mcp_requires_confirm: bool = Field(
        default=True,
        description="Whether MCP clients must confirm before invoking this tool.",
    )
    is_experimental: bool = Field(
        default=False,
        description="Whether this tool is experimental / unstable.",
    )

    model_config = {"extra": "forbid"}
