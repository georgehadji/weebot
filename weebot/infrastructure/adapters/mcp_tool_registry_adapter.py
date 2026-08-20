"""Thin adapter wrapping a role-based registry for scoped retrieval."""

from __future__ import annotations

from typing import Any

from weebot.application.ports.mcp_tool_registration_port import McpToolRegistrationPort


class RoleBasedToolRegistryAdapter(McpToolRegistrationPort):
    """Adapter that satisfies McpToolRegistrationPort over any registry-like object.

    The wrapped object must expose ``add_tool_to_role``, ``remove_tool_from_role``,
    ``add_role``, and ``list_roles`` methods.  We use ``Any`` to avoid importing
    ``weebot.tools.tool_registry`` from infrastructure, which would transitively
    pull in application-layer modules and break Clean Architecture boundaries.
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def add_tool_to_role(self, role: str, tool_name: str) -> None:
        try:
            self._registry.add_tool_to_role(role, tool_name)
        except ValueError:
            # Role may not exist yet; create it with this tool.
            self._registry.add_role(role, [tool_name])

    def remove_tool_from_role(self, role: str, tool_name: str) -> None:
        self._registry.remove_tool_from_role(role, tool_name)

    def list_roles(self) -> list[str]:
        return self._registry.list_roles()
