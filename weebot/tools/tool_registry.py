"""Role-based tool registry for controlling agent tool access."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.tools.base import ToolCollection
    from weebot.application.services.capability_gate import CapabilityGate

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
            "search_images",
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
            "reasoner",
            "berb",
            "spacescraper",
        ],
        "analyst": [
            "python_execute",
            "file_editor",
            "knowledge",
            "bash",
            "reasoner",
            "berb",
            "spacescraper",
        ],
        "automation": [
            "bash",
            "computer_use",
            "screen_capture",
            "schedule",
            "file_editor",
            "python_execute",
            "video_gen",
            "search_images",
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
            "search_images",
            "design_system",
            "persistent_memory",
            "mixture_of_agents",
            "atomic_mail",
            "reasoner",
            "berb",
            "spacescraper",
        ],
        "coder": [
            "bash",
            "python_execute",
            "file_editor",
            "web_search",
            "search_images",
            "image_gen",
            "video_gen",
        ],
        "designer": [
            "search_images",
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
    _TOOL_CLASS_MAP: dict[str, type] | None = None

    # Capability tiers per tool (Capability 4).
    # Maps tool name -> tier string. Default is "public".
    _TOOL_TIERS: dict[str, str] = {
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
        "reasoner": "controlled",
        "berb": "controlled",
        # Everything else defaults to "public" via get_tool_tier()
    }

    def __init__(self, role_mappings: dict[str, list[str]] | None = None) -> None:
        """Initialize the registry.

        Args:
            role_mappings: Optional custom role-to-tools mappings.
                          If None, uses DEFAULT_ROLE_MAPPINGS merged with
                          autodiscovered tool declarations.
        """
        if role_mappings:
            self.role_mappings = role_mappings
        else:
            # Prefer autodiscovered role mappings from tool classes
            auto = self._build_role_mappings_from_class_map()
            if auto:
                self.role_mappings = auto
            else:
                self.role_mappings = dict(self.DEFAULT_ROLE_MAPPINGS)
        logger.info(f"Initialized RoleBasedToolRegistry with {len(self.role_mappings)} roles")

    def get_profile_for_role(self, role: str) -> Any:
        """Return the ExpertProfile for a role, or None if unregistered."""
        try:
            from weebot.domain.models.expert_profile import get_expert_profile
            return get_expert_profile(role)
        except ImportError:
            return None

    def get_tools_for_role(self, role: str) -> list[str]:
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

    def add_role(self, role: str, tools: list[str]) -> None:
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

    def list_roles(self) -> list[str]:
        """Get list of all available roles."""
        return list(self.role_mappings.keys())

    def list_all_tools(self) -> list[str]:
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
        gate: CapabilityGate,
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

    def get_registry_summary(self) -> dict[str, dict]:
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
    def build_tool_class_map(cls) -> dict[str, type]:
        """Lazy-build a mapping from ``BaseTool.name`` -> tool class.

        Uses ``pkgutil.iter_modules`` to auto-discover tool modules in
        ``weebot/tools/``, then checks each for ``BaseTool`` subclasses.
        The map is cached as a class-level singleton.

        Import errors for individual tools are logged and skipped — one
        broken tool does not block the entire registry.
        """
        if cls._TOOL_CLASS_MAP is not None:
            return cls._TOOL_CLASS_MAP

        import importlib
        import pkgutil
        from weebot.tools.base import BaseTool

        cls._TOOL_CLASS_MAP = {}

        import weebot.tools as _tools_pkg
        for _importer, modname, is_pkg in pkgutil.walk_packages(
            path=_tools_pkg.__path__,
            prefix="weebot.tools.",
            onerror=lambda _: None,
        ):
            if is_pkg or modname.endswith("__init__") or modname.endswith("base"):
                continue
            try:
                mod = importlib.import_module(modname)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseTool)
                        and attr is not BaseTool
                    ):
                        try:
                            # Instantiate to read Pydantic field `name`
                            instance = attr()
                            tool_name = instance.name
                            if tool_name and tool_name not in cls._TOOL_CLASS_MAP:
                                cls._TOOL_CLASS_MAP[tool_name] = attr
                        except Exception:
                            continue
            except Exception as exc:
                logger.debug("Tool auto-discovery skipped %s: %s", modname, exc)

        if not cls._TOOL_CLASS_MAP:
            logger.warning("Tool auto-discovery returned no tools — registry will be empty!")

        return cls._TOOL_CLASS_MAP

    @classmethod
    def _build_role_mappings_from_class_map(cls) -> dict[str, list[str]]:
        """Build role→tool mappings from ``BaseTool.allowed_roles`` attributes.

        Iterates over the class map and groups tools by the roles listed
        in their ``allowed_roles`` field.  Tools with ``allowed_roles=["*"]``
        are assigned to a ``"*"`` key (all roles).  The primary use case
        is to replace the hardcoded ``DEFAULT_ROLE_MAPPINGS``.

        Returns:
            Dict mapping role name to list of tool name strings, or empty
            dict if the class map is not yet built or all tools are universal.
        """
        class_map = cls.build_tool_class_map()
        mappings: dict[str, list[str]] = {}
        universal: list[str] = []

        for tool_name, tool_class in class_map.items():
            allowed = getattr(tool_class, "allowed_roles", ["*"])
            if not allowed or "*" in allowed:
                universal.append(tool_name)
                continue
            for role in allowed:
                mappings.setdefault(role, []).append(tool_name)

        # If all tools are universal, return empty (caller falls back to DEFAULT_ROLE_MAPPINGS)
        if not mappings:
            return {}

        # Merge universal tools into every role
        for role in mappings:
            mappings[role].extend(universal)

        return mappings

    def create_tool_collection(
        self,
        role: str,
        llm_port: Any | None = None,
        sandbox_port: Any | None = None,
        tool_config: Any | None = None,
        flow_factory: Any | None = None,
    ) -> ToolCollection:
        """Create a :class:`ToolCollection` with instantiated tools for *role*.

        Args:
            role: Agent role name (must exist in the registry).
            llm_port: Optional LLMPort for tools that support it.
            sandbox_port: Optional SandboxPort for tools that support it.
            tool_config: Optional ToolConfig for tools that support it.
            flow_factory: Optional flow factory callable for sub-agent tools.

        Returns:
            ToolCollection populated with ``BaseTool`` instances.
        """

        tool_names = self.get_tools_for_role(role)
        return self.create_tool_collection_from_names(
            tool_names, llm_port=llm_port,
            sandbox_port=sandbox_port,
            tool_config=tool_config,
            flow_factory=flow_factory,
        )

    def create_tool_collection_from_names(
        self,
        tool_names: list[str],
        llm_port: Any | None = None,
        sandbox_port: Any | None = None,
        tool_config: Any | None = None,
        flow_factory: Any | None = None,
    ) -> ToolCollection:
        """Create a :class:`ToolCollection` from an explicit list of tool names.

        Args:
            tool_names: List of ``BaseTool.name`` strings.
            llm_port: Optional LLMPort for tools that support it (e.g., BrowserTool).
            sandbox_port: Optional SandboxPort.
            tool_config: Optional ToolConfig.
            flow_factory: Optional flow factory callable for sub-agent tools.

        Returns:
            ToolCollection with matching ``BaseTool`` instances.
            Unknown names are logged and silently skipped.
        """
        from weebot.tools.base import ToolCollection

        class_map = self.build_tool_class_map()
        tools: list = []
        # Tools that accept an injected LLMPort via their Pydantic field
        _llm_port_tools = {"browser_navigator", "mixture_of_agents"}
        # Tools that need flow_factory and llm
        _flow_factory_llm_tools = {"debate", "swarm"}
        # Tools that need flow_factory and optionally state_repo (no llm)
        _flow_factory_state_tools = {"dispatch_parallel_tasks", "workflow_orchestrator"}
        # Tools that share a single PlaywrightAdapter instance
        _browser_adapter_tools = {"advanced_browser", "browser_inspector"}
        _shared_browser_adapter = None

        for name in tool_names:
            tool_cls = class_map.get(name)
            if tool_cls is not None:
                # If flow_factory is required but not provided, try to resolve it from the container
                if name in _flow_factory_llm_tools or name in _flow_factory_state_tools:
                    if flow_factory is None:
                        try:
                            import importlib as _il
                            _c_mod = _il.import_module("weebot.application.di")
                            _c = _c_mod.Container()
                            _c.configure_defaults()
                            flow_factory = lambda session: _c._build_plan_act_flow_for_session(session)
                        except Exception:
                            pass

                if name in _llm_port_tools and llm_port is not None:
                    tool = tool_cls(llm_port=llm_port)
                elif name in _flow_factory_llm_tools:
                    tool = tool_cls(llm=llm_port, flow_factory=flow_factory)
                elif name in _flow_factory_state_tools:
                    state_repo = None
                    try:
                        import importlib as _il
                        _state_repo_mod = _il.import_module("weebot.application.ports.state_repo_port")
                        StateRepositoryPort = _state_repo_mod.StateRepositoryPort
                        _c = _il.import_module("weebot.application.di").Container()
                        _c.configure_defaults()
                        state_repo = _c.get(StateRepositoryPort)
                    except Exception:
                        pass
                    # ponytail: support state_repo injection cleanly
                    tool = tool_cls(flow_factory=flow_factory, state_repo=state_repo)
                elif name in _browser_adapter_tools:
                    if _shared_browser_adapter is None:
                        from weebot.infrastructure.browser.playwright_adapter import (
                            PlaywrightAdapter,
                        )
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
                        import importlib as _il
                        _rerank_mod = _il.import_module("weebot.application.ports.rerank_port")
                        RerankPort = _rerank_mod.RerankPort
                        _c = _il.import_module("weebot.application.di").Container()
                        _c.configure_defaults()
                        rerank = _c.get(RerankPort)
                        tool.set_rerank(rerank)
                        logger.debug("Injected RerankPort into %s", name)
                    except Exception:
                        pass  # RerankPort not configured — fall back to engine order
                tools.append(tool)
            else:
                logger.warning("Tool %r not found in class map, skipping", name)
        return ToolCollection(*tools)
