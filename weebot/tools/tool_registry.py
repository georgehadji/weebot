"""Role-based tool registry for controlling agent tool access."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from weebot.tools.base import BaseTool, ToolCollection

logger = logging.getLogger(__name__)


class RoleBasedToolRegistry:
    """Registry mapping agent roles to authorized tools.

    Controls which tools each agent role can access, enabling fine-grained
    access control in multi-agent workflows.

    Tool names MUST match the ``name`` attribute on the corresponding
    ``BaseTool`` subclass (e.g. ``"bash"`` not ``"bash_tool"``).
    """

    # Define roles and their authorized tools.
    # Names match BaseTool.name on each concrete tool class.
    DEFAULT_ROLE_MAPPINGS = {
        "researcher": [
            "web_search",
            "advanced_browser",
            "file_editor",
            "knowledge",
            "video_ingest",
            "screen_capture",
        ],
        "analyst": [
            "python_execute",
            "file_editor",
            "knowledge",
            "bash",
        ],
        "automation": [
            "bash",
            "computer_use",
            "screen_capture",
            "schedule",
            "file_editor",
            "python_execute",
        ],
        "documentation": [
            "file_editor",
            "knowledge",
            "web_search",
            "product",
        ],
        "product_manager": [
            "product",
            "file_editor",
            "knowledge",
            "bash",
        ],
        "admin": [
            "web_search",
            "advanced_browser",
            "file_editor",
            "knowledge",
            "video_ingest",
            "python_execute",
            "bash",
            "computer_use",
            "screen_capture",
            "schedule",
            "product",
            "powershell",
            "terminate",
            "ask_human",
            "ocr",
        ],
        "custom": [],  # Custom roles have no default tools
    }

    # Lazy singleton: BaseTool.name -> tool class.
    _TOOL_CLASS_MAP: Optional[Dict[str, type]] = None

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

    # ------------------------------------------------------------------
    # Tool instantiation (Phase 2)
    # ------------------------------------------------------------------

    @classmethod
    def _build_tool_class_map(cls) -> Dict[str, type]:
        """Lazy-build a mapping from ``BaseTool.name`` -> tool class.

        Imports are deferred to avoid circular imports at module load time.
        The map is cached as a class-level singleton.
        """
        if cls._TOOL_CLASS_MAP is not None:
            return cls._TOOL_CLASS_MAP

        from weebot.tools.bash_tool import BashTool
        from weebot.tools.python_tool import PythonExecuteTool
        from weebot.tools.web_search import WebSearchTool
        from weebot.tools.file_editor import StrReplaceEditorTool
        from weebot.tools.advanced_browser import AdvancedBrowserTool
        from weebot.tools.computer_use import ComputerUseTool
        from weebot.tools.screen_tool import ScreenCaptureBaseTool
        from weebot.tools.schedule_tool import ScheduleTool
        from weebot.tools.knowledge_tool import KnowledgeTool
        from weebot.tools.product_tool import ProductTool
        from weebot.tools.video_ingest_tool import VideoIngestTool
        from weebot.tools.powershell_tool import PowerShellBaseTool
        from weebot.tools.ocr import OCRTool
        from weebot.tools.control import TerminateTool, AskHumanTool

        cls._TOOL_CLASS_MAP = {
            "bash": BashTool,
            "python_execute": PythonExecuteTool,
            "web_search": WebSearchTool,
            "file_editor": StrReplaceEditorTool,
            "advanced_browser": AdvancedBrowserTool,
            "computer_use": ComputerUseTool,
            "screen_capture": ScreenCaptureBaseTool,
            "schedule": ScheduleTool,
            "knowledge": KnowledgeTool,
            "product": ProductTool,
            "video_ingest": VideoIngestTool,
            "powershell": PowerShellBaseTool,
            "ocr": OCRTool,
            "terminate": TerminateTool,
            "ask_human": AskHumanTool,
        }
        return cls._TOOL_CLASS_MAP

    def create_tool_collection(self, role: str) -> "ToolCollection":
        """Create a :class:`ToolCollection` with instantiated tools for *role*.

        Args:
            role: Agent role name (must exist in the registry).

        Returns:
            ToolCollection populated with ``BaseTool`` instances.
        """
        from weebot.tools.base import ToolCollection

        tool_names = self.get_tools_for_role(role)
        return self.create_tool_collection_from_names(tool_names)

    def create_tool_collection_from_names(
        self, tool_names: List[str],
    ) -> "ToolCollection":
        """Create a :class:`ToolCollection` from an explicit list of tool names.

        Args:
            tool_names: List of ``BaseTool.name`` strings.

        Returns:
            ToolCollection with matching ``BaseTool`` instances.
            Unknown names are logged and silently skipped.
        """
        from weebot.tools.base import ToolCollection

        class_map = self._build_tool_class_map()
        tools: list = []
        for name in tool_names:
            tool_cls = class_map.get(name)
            if tool_cls is not None:
                tools.append(tool_cls())
            else:
                logger.warning("Tool %r not found in class map, skipping", name)
        return ToolCollection(*tools)
