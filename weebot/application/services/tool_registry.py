"""Role-based tool registry for controlling agent tool access."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.application.models.tool_collection import ToolCollection

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
            "moli_fetch",
            "agent_reach",
            "camofox_browser",
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
            "youtube_download",
            "web_scraper",
            "ocr_structured",
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
            "remotion_video",
            "search_images",
            "atomic_mail",
        ],
        "documentation": ["file_editor", "knowledge", "web_search", "product"],
        "product_manager": ["product", "file_editor", "knowledge", "bash"],
        "admin": [
            "web_search",
            "vane_search",
            "image_gen",
            "video_gen",
            "remotion_video",
            "advanced_browser",
            "moli_fetch",
            "agent_reach",
            "camofox_browser",
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
            # In no role before (F53); skills name youtube_download and desktop_a11y.
            "youtube_download",
            "desktop_a11y",
            "detect_elements",
            "screenshot_ocr",
            "ocr_structured",
            "web_scraper",
        ],
        "webhook": [
            # Admin-level tools minus exec tools (bash, powershell, python_execute)
            # and minus terminate — webhooks should not exec arbitrary code by default.
            # Also out: spacescraper (docker-compose up), computer_use (types into
            # any window), design_system (npm install -g) (F66).
            "web_search",
            "vane_search",
            "image_gen",
            "video_gen",
            "remotion_video",
            "advanced_browser",
            "moli_fetch",
            "agent_reach",
            "camofox_browser",
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
            "screen_capture",
            "schedule",
            "product",
            "ask_human",
            "ocr",
            "weather",
            "search_images",
            "persistent_memory",
            "mixture_of_agents",
            "atomic_mail",
            "reasoner",
            "berb",
        ],
        "coder": [
            "bash",
            "python_execute",
            "file_editor",
            "web_search",
            "search_images",
            "image_gen",
            "video_gen",
            "remotion_video",
        ],
        "designer": [
            "search_images",
            "image_gen",
            "video_gen",
            "remotion_video",
            "file_editor",
            "browser_inspector",
            "web_search",
        ],
        "reviewer": ["file_editor", "web_search", "knowledge"],
        "planner_sub": ["file_editor", "knowledge", "web_search"],
        "custom": [],  # Custom roles have no default tools
    }

    # Lazy singleton: BaseTool.name -> tool class.
    _TOOL_CLASS_MAP: dict[str, type] | None = None

    def __init__(
        self,
        role_mappings: dict[str, list[str]] | None = None,
        wiring: Any | None = None,
    ) -> None:
        """Initialize the registry.

        Args:
            role_mappings: Optional custom role-to-tools mappings.
                          If None, uses DEFAULT_ROLE_MAPPINGS, the one role
                          table (F32: the old ``allowed_roles`` autodiscovery
                          could never take effect and was deleted).
            wiring: Optional zero-argument callable returning the collaborators
                every collection from this registry gets: ``state_repo``,
                ``rerank``, ``tool_config``, ``sandbox_port``, and
                ``collaborators`` (tool name -> constructor kwargs). The DI
                container supplies it (W5.5); an argument a caller passes wins.
        """
        self._wiring = wiring
        # Copies all the way down (F33): a shallow copy shared the lists, and
        # add_tool_to_role on one registry changed every later one.
        source = role_mappings or self.DEFAULT_ROLE_MAPPINGS
        self.role_mappings = {role: list(tools) for role, tools in source.items()}
        logger.info(f"Initialized RoleBasedToolRegistry with {len(self.role_mappings)} roles")

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
            raise ValueError(f"Unknown role '{role}'. Available roles: {available_roles}")

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

    def get_registry_summary(self) -> dict[str, dict]:
        """Get a summary of all role-to-tools mappings.

        Returns:
            Dictionary with role metadata
        """
        return {
            role: {"tools": tools, "tool_count": len(tools)}
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
        from weebot.domain.models.base_tool import BaseTool

        cls._TOOL_CLASS_MAP = {}

        import weebot.tools as _tools_pkg

        for _importer, modname, is_pkg in pkgutil.walk_packages(
            path=_tools_pkg.__path__, prefix="weebot.tools.", onerror=lambda _: None
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
                            # The `name` field's default. Instantiating every
                            # tool class to read it built a Container in each
                            # tool that resolves its own collaborators (W5.3).
                            field = attr.model_fields.get("name")
                            tool_name = getattr(field, "default", None)
                            if not isinstance(tool_name, str) or not tool_name:
                                tool_name = attr().name
                            if tool_name and tool_name not in cls._TOOL_CLASS_MAP:
                                cls._TOOL_CLASS_MAP[tool_name] = attr
                        except Exception:
                            continue
            except Exception as exc:
                logger.debug("Tool auto-discovery skipped %s: %s", modname, exc)

        if not cls._TOOL_CLASS_MAP:
            logger.warning("Tool auto-discovery returned no tools — registry will be empty!")

        return cls._TOOL_CLASS_MAP

    def create_tool_collection(
        self,
        role: str,
        llm_port: Any | None = None,
        sandbox_port: Any | None = None,
        tool_config: Any | None = None,
        flow_factory: Any | None = None,
        state_repo: Any | None = None,
        rerank: Any | None = None,
    ) -> ToolCollection:
        """Create a :class:`ToolCollection` with instantiated tools for *role*.

        Args:
            role: Agent role name (must exist in the registry).
            llm_port: Optional LLMPort for tools that support it.
            sandbox_port: Optional SandboxPort for tools that support it.
            tool_config: Optional ToolConfig for tools that support it.
            flow_factory: Optional flow factory callable for sub-agent tools.
            state_repo: Optional StateRepositoryPort for the sub-agent tools.
            rerank: Optional RerankPort for tools with ``set_rerank``.

        Returns:
            ToolCollection populated with ``BaseTool`` instances.
        """

        tool_names = self.get_tools_for_role(role)
        return self.create_tool_collection_from_names(
            tool_names,
            llm_port=llm_port,
            sandbox_port=sandbox_port,
            tool_config=tool_config,
            flow_factory=flow_factory,
            state_repo=state_repo,
            rerank=rerank,
        )

    def create_tool_collection_from_names(
        self,
        tool_names: list[str],
        llm_port: Any | None = None,
        sandbox_port: Any | None = None,
        tool_config: Any | None = None,
        flow_factory: Any | None = None,
        state_repo: Any | None = None,
        rerank: Any | None = None,
    ) -> ToolCollection:
        """Create a :class:`ToolCollection` from an explicit list of tool names.

        Args:
            tool_names: List of ``BaseTool.name`` strings.
            llm_port: Optional LLMPort for tools that support it (e.g., BrowserTool).
            sandbox_port: Optional SandboxPort.
            tool_config: Optional ToolConfig.
            flow_factory: Optional flow factory callable for sub-agent tools.
            state_repo: Optional StateRepositoryPort for the sub-agent tools.
            rerank: Optional RerankPort for tools with ``set_rerank``.

        Collaborators come from the caller, else from the registry's
        ``wiring``. A tool with constructor collaborators of its own (audit,
        knowledge, persistent memory, video ingest, voice in/out) gets them
        from ``wiring()["collaborators"]`` and is skipped without them; these
        tools used to build a whole Container() each (W5.3, W5.5, F28, F35).

        Returns:
            ToolCollection with matching ``BaseTool`` instances.
            Unknown names are logged and silently skipped.
        """
        from weebot.application.models.tool_collection import ToolCollection

        wired = self._wiring() if self._wiring is not None else {}
        sandbox_port = sandbox_port if sandbox_port is not None else wired.get("sandbox_port")
        tool_config = tool_config if tool_config is not None else wired.get("tool_config")
        state_repo = state_repo if state_repo is not None else wired.get("state_repo")
        rerank = rerank if rerank is not None else wired.get("rerank")
        collaborators: dict[str, dict] = wired.get("collaborators") or {}
        browser_factory = wired.get("browser_factory")
        workflow_events = wired.get("workflow_events")

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
        # Tools that accept an injected SandboxPort for shell/code execution.
        # When sandbox_port is None each of these resolves its own default via
        # weebot.infrastructure.sandbox.factory.create_default_sandbox().
        _sandbox_port_tools = {"bash", "powershell", "python_execute"}

        for name in tool_names:
            tool_cls = class_map.get(name)
            if tool_cls is not None:
                if name in collaborators:
                    try:
                        tool = tool_cls(**collaborators[name])
                    except (TypeError, RuntimeError) as exc:
                        logger.debug("Skipping tool %s: construction failed (%s)", name, exc)
                        continue
                elif name in _llm_port_tools and llm_port is not None:
                    tool = tool_cls(llm_port=llm_port)
                elif name in _sandbox_port_tools and sandbox_port is not None:
                    tool = tool_cls(sandbox=sandbox_port)
                elif name == "swarm":
                    # The swarm tool receives its agents instead of importing them (plan 3.3).
                    from weebot.application.agents.goal_agent import GoalAgent
                    from weebot.application.agents.synthesizer_agent import SynthesizerAgent

                    tool = tool_cls(
                        llm=llm_port,
                        flow_factory=flow_factory,
                        decompose=GoalAgent(llm_port).decompose,
                        synthesize=SynthesizerAgent(llm_port).synthesize,
                    )
                elif name in _flow_factory_llm_tools:
                    tool = tool_cls(llm=llm_port, flow_factory=flow_factory)
                elif name == "workflow_orchestrator":
                    tool = tool_cls(
                        flow_factory=flow_factory,
                        state_repo=state_repo,
                        event_publisher=workflow_events,
                    )
                elif name in _flow_factory_state_tools:
                    tool = tool_cls(flow_factory=flow_factory, state_repo=state_repo)
                elif name in _browser_adapter_tools:
                    # The browser comes from the composition root (wiring["browser_factory"]),
                    # one instance shared by the browser tools; this module imports no adapter.
                    if _shared_browser_adapter is None and browser_factory is not None:
                        _shared_browser_adapter = browser_factory()
                    if _shared_browser_adapter is None:
                        logger.debug("Skipping tool %s: no browser_factory wired", name)
                        continue
                    tool = tool_cls(browser=_shared_browser_adapter)
                else:
                    try:
                        tool = tool_cls()
                    except (TypeError, RuntimeError) as exc:
                        logger.debug(
                            "Skipping tool %s: construction failed (%s). "
                            "This tool requires DI injection.",
                            name,
                            exc,
                        )
                        continue
                # Inject tool_config after construction if tool supports it
                if tool_config is not None and hasattr(tool, "set_config"):
                    tool.set_config(tool_config)
                # Inject RerankPort if tool supports it (WebSearchTool).
                # None: no reranker configured, results keep engine order.
                if rerank is not None and hasattr(tool, "set_rerank"):
                    tool.set_rerank(rerank)
                tools.append(tool)
            else:
                logger.warning("Tool %r not found in class map, skipping", name)
        # Every code-running tool goes through the one guard chain (ICM fix
        # plan W3.2, F01): powershell used to skip BashGuard and the analyzer.
        # No egress guard here: collections run under ToolExecutor, which
        # gates egress itself (ADR-013; one approval per call).
        from weebot.application.services.tool_guards import guard_tools

        return ToolCollection(*guard_tools(tools, include_egress=False))
