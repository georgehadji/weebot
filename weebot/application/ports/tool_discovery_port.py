"""ToolDiscoveryPort — abstract interface for discovering available agent tools.

Implementations introspect the tool registry and return structured
:class:`~weebot.domain.models.tool_manifest.ToolManifest` records.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.tool_manifest import ToolManifest


class ToolDiscoveryPort(ABC):
    """Abstract interface for tool discovery.

    Decouples tool introspection (infrastructure concern) from consumers
    like the MCP server, CLI, and web UI (interface layer).
    """

    @abstractmethod
    async def list_tools(self, role: str | None = None) -> list[ToolManifest]:
        """Return manifests for all discoverable tools.

        Args:
            role: Optional role filter. When provided, only tools accessible
                  to that role are returned.  When ``None``, all tools are
                  returned regardless of role access.

        Returns:
            List of tool manifests, sorted alphabetically by name.
        """
        ...

    @abstractmethod
    async def get_tool(self, name: str) -> ToolManifest | None:
        """Return a single tool manifest by name, or ``None`` if not found."""
        ...
