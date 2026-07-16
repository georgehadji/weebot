"""McpToolRegistrationPort — abstract interface over tool registry mutations.

This port decouples scoped retrieval orchestration from the concrete
RoleBasedToolRegistry implementation, satisfying the Clean Architecture
dependency rule.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class McpToolRegistrationPort(ABC):
    """Mutation surface used by scoped retrieval to sync tools into roles."""

    @abstractmethod
    def add_tool_to_role(self, role: str, tool_name: str) -> None:
        """Add *tool_name* to the tool list for *role*."""
        ...

    @abstractmethod
    def remove_tool_from_role(self, role: str, tool_name: str) -> None:
        """Remove *tool_name* from the tool list for *role*."""
        ...

    @abstractmethod
    def list_roles(self) -> list[str]:
        """Return all known role names."""
        ...
