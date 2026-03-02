"""Role-based tool registry for controlling agent tool access."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RoleBasedToolRegistry:
    """Registry mapping agent roles to authorized tools.

    Controls which tools each agent role can access, enabling fine-grained
    access control in multi-agent workflows.
    """

    # Define roles and their authorized tools
    DEFAULT_ROLE_MAPPINGS = {
        "researcher": [
            "web_search",
            "advanced_browser",
            "file_editor",
            "knowledge_tool",
            "video_ingest_tool",
            "screen_tool"
        ],
        "analyst": [
            "python_tool",
            "file_editor",
            "knowledge_tool",
            "bash_tool"
        ],
        "automation": [
            "bash_tool",
            "computer_use",
            "screen_tool",
            "schedule_tool",
            "file_editor",
            "python_tool"
        ],
        "documentation": [
            "file_editor",
            "knowledge_tool",
            "web_search",
            "product_tool"
        ],
        "product_manager": [
            "product_tool",
            "file_editor",
            "knowledge_tool",
            "bash_tool"
        ],
        "admin": [
            # Admin has access to all tools
            "web_search",
            "advanced_browser",
            "file_editor",
            "knowledge_tool",
            "video_ingest_tool",
            "python_tool",
            "bash_tool",
            "computer_use",
            "screen_tool",
            "schedule_tool",
            "product_tool",
            "powershell_tool",
            "control",
            "ocr"
        ],
        "custom": []  # Custom roles have no default tools
    }

    def __init__(self, role_mappings: Optional[Dict[str, List[str]]] = None) -> None:
        """Initialize the registry.

        Args:
            role_mappings: Optional custom role-to-tools mappings.
                          If None, uses DEFAULT_ROLE_MAPPINGS.
        """
        self.role_mappings = role_mappings or dict(self.DEFAULT_ROLE_MAPPINGS)
        logger.info(f"Initialized RoleBasedToolRegistry with {len(self.role_mappings)} roles")

    def get_tools_for_role(self, role: str) -> List[str]:
        """Get the list of authorized tools for a given role.

        Args:
            role: The role name

        Returns:
            List of tool names authorized for this role

        Raises:
            ValueError: If role is not recognized
        """
        if role not in self.role_mappings:
            available_roles = ", ".join(self.role_mappings.keys())
            raise ValueError(
                f"Unknown role '{role}'. Available roles: {available_roles}"
            )

        tools = self.role_mappings[role]
        logger.debug(f"Role '{role}' has access to {len(tools)} tools: {tools}")
        return tools

    def add_role(self, role: str, tools: List[str]) -> None:
        """Add or update a role with specific tools.

        Args:
            role: Role name
            tools: List of tool names
        """
        self.role_mappings[role] = tools
        logger.info(f"Added/updated role '{role}' with {len(tools)} tools")

    def add_tool_to_role(self, role: str, tool: str) -> None:
        """Add a single tool to a role's authorized tools.

        Args:
            role: Role name
            tool: Tool name to add

        Raises:
            ValueError: If role doesn't exist
        """
        if role not in self.role_mappings:
            raise ValueError(f"Unknown role '{role}'")

        if tool not in self.role_mappings[role]:
            self.role_mappings[role].append(tool)
            logger.info(f"Added tool '{tool}' to role '{role}'")

    def remove_tool_from_role(self, role: str, tool: str) -> None:
        """Remove a tool from a role's authorized tools.

        Args:
            role: Role name
            tool: Tool name to remove

        Raises:
            ValueError: If role doesn't exist
        """
        if role not in self.role_mappings:
            raise ValueError(f"Unknown role '{role}'")

        if tool in self.role_mappings[role]:
            self.role_mappings[role].remove(tool)
            logger.info(f"Removed tool '{tool}' from role '{role}'")

    def validate_tool_for_role(self, role: str, tool: str) -> bool:
        """Check if a role has access to a specific tool.

        Args:
            role: Role name
            tool: Tool name

        Returns:
            True if role can access tool, False otherwise
        """
        try:
            allowed_tools = self.get_tools_for_role(role)
            return tool in allowed_tools
        except ValueError:
            return False

    def list_roles(self) -> List[str]:
        """Get list of all available roles."""
        return list(self.role_mappings.keys())

    def list_all_tools(self) -> List[str]:
        """Get deduplicated list of all tools across all roles."""
        all_tools = set()
        for tools in self.role_mappings.values():
            all_tools.update(tools)
        return sorted(list(all_tools))

    def get_registry_summary(self) -> Dict[str, Dict]:
        """Get a summary of all role-to-tools mappings.

        Returns:
            Dictionary with role metadata
        """
        return {
            role: {
                "tools": tools,
                "tool_count": len(tools)
            }
            for role, tools in self.role_mappings.items()
        }
