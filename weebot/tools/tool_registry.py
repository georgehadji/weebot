"""Role-based tool registry for controlling agent tool access."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from weebot.tools.base import BaseTool, ToolCollection
    from weebot.application.services.capability_gate import CapabilityGate
    from weebot.domain.models.capability_tier import CapabilityTier

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
            "vane_search",
            "advanced_browser",
            "browser_inspector",
            "file_editor",
            "knowledge",
            "video_ingest",
            "screen_capture",
            "weather",
            "swarm",
            "debate",
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
            "video_gen",
            "atomic_mail",
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
            "vane_search",
            "image_gen",
            "video_gen",
            "advanced_browser",
            "browser_navigator",
            "browser_inspector",
            "dispatch_parallel_tasks",
            "workflow_orchestrator",
            "swarm",
            "debate",
            "search_history",
            "todo_write",
            "audit_session",
            "voice_input",
            "voice_output",
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
            "weather",
            "design_system",
            "persistent_memory",
            "mixture_of_agents",
            "atomic_mail",
        ],
        "coder": [
            "bash",
            "python_execute",
            "file_editor",
            "web_search",
            "image_gen",
            "video_gen",
        ],
        "designer": [
            "image_gen",
            "video_gen",
            "file_editor",
            "browser_inspector",
            "web_search",
        ],
        "reviewer": [
            "file_editor",
            "web_search",
            "knowledge",
        ],
        "planner_sub": [
            "file_editor",
            "knowledge",
            "web_search",
        ],
        "custom": [],  # Custom roles have no default tools
    }

    # Lazy singleton: BaseTool.name -> tool class.
    _TOOL_CLASS_MAP: Optional[Dict[str, type]] = None

    # Capability tiers per tool (Capability 4).
    # Maps tool name -> tier string. Default is "public".
    _TOOL_TIERS: Dict[str, str] = {
        "bash": "restricted",
        "computer_use": "privileged",
        "powershell": "restricted",
        "python_execute": "controlled",
        "file_editor": "controlled",
        "schedule": "controlled",
        "dispatch_parallel_tasks": "restricted",
        "terminate": "privileged",
        "persistent_memory": "controlled",
        "advanced_browser": "controlled",
        "screen_capture": "restricted",
        "swarm": "controlled",
        "debate": "controlled",
        "mixture_of_agents": "controlled",
        "audit_session": "restricted",
        # Everything else defaults to "public" via get_tool_tier()
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

    def get_tool_tier(self, tool_name: str) -> str:
        """Get the capability tier for a tool.

        Args:
            tool_name: The tool's name (e.g. "bash", "file_editor").

        Returns:
            Tier string: "public", "controlled", "restricted", or "privileged".
        """
        return self._TOOL_TIERS.get(tool_name, "public")

    def set_tool_tier(self, tool_name: str, tier: str) -> None:
        """Set the access tier for a tool.

        Args:
            tool_name: The tool''s name.
            tier: One of "public", "controlled", "restricted", "privileged".
        """
        self._TOOL_TIERS[tool_name] = tier

    def get_tools_for_role_with_gate(
        self,
        role: str,
        gate: "CapabilityGate",
        context: dict[str, Any],
    ) -> list[str]:
        """Get tools for a role, filtered by capability tier gate.

        Args:
            role: The role name.
            gate: CapabilityGate instance for tier checking.
            context: Context dict passed to gate.check().

        Returns:
            List of tool names that passed the tier gate.
        """
        all_tools = self.get_tools_for_role(role)
        passed: list[str] = []
        for tool_name in all_tools:
            tier_str = self.get_tool_tier(tool_name)
            from weebot.domain.models.capability_tier import CapabilityTier
            try:
                tier = CapabilityTier(tier_str)
            except ValueError:
                tier = CapabilityTier.PUBLIC
            allowed, _reason = gate.check(tier, context)
            if allowed:
                passed.append(tool_name)
            else:
                logger.info(
                    "Tool '%s' excluded from role '%s' by capability gate (tier: %s)",
                    tool_name, role, tier_str,
                )
        return passed

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
        from weebot.tools.powershell_tool import PowerShellTool
        from weebot.tools.ocr import OCRTool
        from weebot.tools.weather_tool import WeatherTool
        from weebot.tools.design_system_tool import DesignSystemTool
        from weebot.tools.control import TerminateTool, AskHumanTool
        from weebot.tools.browser_inspector import BrowserInspectorTool
        from weebot.tools.dispatch_agents import DispatchAgentsTool
        from weebot.tools.persistent_memory import PersistentMemoryTool
        from weebot.tools.mixture_of_agents import MixtureOfAgentsTool
        from weebot.tools.swarm import SwarmTool
        from weebot.tools.debate import DebateTool
        from weebot.tools.search_history import SearchHistoryTool
        from weebot.tools.todo_tool import TodoWriteTool
        from weebot.tools.audit_tool import AuditTool
        from weebot.tools.voice_input_tool import VoiceInputTool
        from weebot.tools.voice_output_tool import VoiceOutputTool
        from weebot.tools.browser_tool import BrowserTool
        from weebot.tools.workflow_orchestrator import WorkflowOrchestratorTool
        from weebot.tools.vane_search import VaneSearchTool
        from weebot.tools.image_gen_tool import ImageGenTool
        from weebot.tools.video_gen_tool import VideoGenTool

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
            "powershell": PowerShellTool,
            "ocr": OCRTool,
            "weather": WeatherTool,
            "design_system": DesignSystemTool,
            "terminate": TerminateTool,
            "ask_human": AskHumanTool,
            "browser_inspector": BrowserInspectorTool,
            "dispatch_parallel_tasks": DispatchAgentsTool,
            "persistent_memory": PersistentMemoryTool,
            "mixture_of_agents": MixtureOfAgentsTool,
            "swarm": SwarmTool,
            "debate": DebateTool,
            "search_history": SearchHistoryTool,
            "todo_write": TodoWriteTool,
            "audit_session": AuditTool,
            "voice_input": VoiceInputTool,
            "voice_output": VoiceOutputTool,
            "browser_navigator": BrowserTool,
            "workflow_orchestrator": WorkflowOrchestratorTool,
            "vane_search": VaneSearchTool,
            "image_gen": ImageGenTool,
            "video_gen": VideoGenTool,
        }

        if os.getenv("WEEBOT_ENABLE_ATOMIC_MAIL", "0").strip("\"'") not in ("", "0", "false", "False"):
            from weebot.tools.atomic_mail_tool import AtomicMailTool
            cls._TOOL_CLASS_MAP["atomic_mail"] = AtomicMailTool

        return cls._TOOL_CLASS_MAP

    def create_tool_collection(
        self,
        role: str,
        llm_port: Optional[Any] = None,
        sandbox_port: Optional[Any] = None,
        tool_config: Optional[Any] = None,
    ) -> "ToolCollection":
        """Create a :class:`ToolCollection` with instantiated tools for *role*.

        Args:
            role: Agent role name (must exist in the registry).
            llm_port: Optional LLMPort for tools that support it.
            sandbox_port: Optional SandboxPort for tools that support it.
            tool_config: Optional ToolConfig for tools that support it.

        Returns:
            ToolCollection populated with ``BaseTool`` instances.
        """
        from weebot.tools.base import ToolCollection

        tool_names = self.get_tools_for_role(role)
        return self.create_tool_collection_from_names(
            tool_names, llm_port=llm_port,
            sandbox_port=sandbox_port,
            tool_config=tool_config,
        )

    def create_tool_collection_from_names(
        self,
        tool_names: List[str],
        llm_port: Optional[Any] = None,
        sandbox_port: Optional[Any] = None,
        tool_config: Optional[Any] = None,
    ) -> "ToolCollection":
        """Create a :class:`ToolCollection` from an explicit list of tool names.

        Args:
            tool_names: List of ``BaseTool.name`` strings.
            llm_port: Optional LLMPort for tools that support it (e.g., BrowserTool).

        Returns:
            ToolCollection with matching ``BaseTool`` instances.
            Unknown names are logged and silently skipped.
        """
        from weebot.tools.base import ToolCollection

        class_map = self._build_tool_class_map()
        tools: list = []
        # Tools that accept an injected LLMPort via their Pydantic field
        _llm_port_tools = {"browser_navigator", "mixture_of_agents"}
        # Tools that share a single PlaywrightAdapter instance
        _browser_adapter_tools = {"advanced_browser", "browser_inspector"}
        _shared_browser_adapter = None

        for name in tool_names:
            tool_cls = class_map.get(name)
            if tool_cls is not None:
                if name in _llm_port_tools and llm_port is not None:
                    tool = tool_cls(llm_port=llm_port)
                elif name in _browser_adapter_tools:
                    if _shared_browser_adapter is None:
                        from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
                        _shared_browser_adapter = PlaywrightAdapter()
                    tool = tool_cls(browser=_shared_browser_adapter)
                else:
                    try:
                        tool = tool_cls()
                    except (TypeError, RuntimeError) as exc:
                        logger.debug(
                            "Skipping tool %s: construction failed (%s). "
                            "This tool requires DI injection.",
                            name, exc,
                        )
                        continue
                # Inject tool_config after construction if tool supports it
                if tool_config is not None and hasattr(tool, "set_config"):
                    tool.set_config(tool_config)
                # Inject RerankPort if tool supports it (WebSearchTool, MultiSourceResearchEngine)
                if hasattr(tool, "set_rerank"):
                    try:
                        from weebot.application.di import Container
                        from weebot.application.ports.rerank_port import RerankPort
                        c = Container()
                        c.configure_defaults()
                        rerank = c.get(RerankPort)
                        tool.set_rerank(rerank)
                        logger.debug("Injected RerankPort into %s", name)
                    except Exception:
                        pass  # RerankPort not configured — fall back to engine order
                tools.append(tool)
            else:
                logger.warning("Tool %r not found in class map, skipping", name)
        return ToolCollection(*tools)
