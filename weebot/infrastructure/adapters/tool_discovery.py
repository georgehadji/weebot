"""ToolDiscoveryAdapter — introspects BaseTool subclasses for manifests.

Implements :class:`~weebot.application.ports.tool_discovery_port.ToolDiscoveryPort`
by discovering all ``BaseTool`` subclasses in ``weebot.tools`` and building
:class:`~weebot.domain.models.tool_manifest.ToolManifest` records from their
class-level metadata.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.tool_discovery_port import ToolDiscoveryPort
from weebot.domain.models.tool_manifest import ToolManifest
from weebot.tools.base import BaseTool
from weebot.tools.tool_registry import RoleBasedToolRegistry

_log = logging.getLogger(__name__)

# ── Tool module import helper ───────────────────────────────────────────

_TOOL_MODULES_IMPORTED = False


def _import_tool_modules() -> None:
    """Import all tool modules so __subclasses__() can discover them."""
    global _TOOL_MODULES_IMPORTED
    if _TOOL_MODULES_IMPORTED:
        return
    _TOOL_MODULES_IMPORTED = True

    # Lazy imports — only import what exists to avoid hard failures
    _TOOL_MODULE_NAMES = [
        "weebot.tools.bash_tool",
        "weebot.tools.powershell_tool",
        "weebot.tools.python_tool",
        "weebot.tools.web_search",
        "weebot.tools.vane_search",
        "weebot.tools.file_editor",
        "weebot.tools.browser_inspector",
        "weebot.tools.advanced_browser",
        "weebot.tools.computer_use",
        "weebot.tools.screen_tool",
        "weebot.tools.ocr",
        "weebot.tools.knowledge_tool",
        "weebot.tools.persistent_memory",
        "weebot.tools.product_tool",
        "weebot.tools.todo_tool",
        "weebot.tools.schedule_tool",
        "weebot.tools.search_history",
        "weebot.tools.weather_tool",
        "weebot.tools.image_gen_tool",
        "weebot.tools.voice_input_tool",
        "weebot.tools.voice_output_tool",
        "weebot.tools.video_ingest_tool",
        "weebot.tools.swarm",
        "weebot.tools.debate",
        "weebot.tools.mixture_of_agents",
        "weebot.tools.dispatch_agents",
        "weebot.tools.workflow_orchestrator",
        "weebot.tools.subagent_rpc",
        "weebot.tools.design_system_tool",
        "weebot.tools.audit_tool",
        "weebot.tools.heuristic_router",
        "weebot.tools.control",
    ]
    for mod_name in _TOOL_MODULE_NAMES:
        try:
            __import__(mod_name)
        except ImportError:
            _log.debug("Tool module not available: %s", mod_name)

# ── Per-tool manifest overrides ──────────────────────────────────────────
# Tools without class-level metadata are described here.  Tools that DO
# declare _manifest_* attributes are discovered automatically.

_MANUAL_MANIFESTS: dict[str, dict] = {
    "bash": {
        "description": "Execute a shell command via PowerShell (Windows) or WSL2 bash. "
                       "Dangerous commands are blocked; destructive commands require confirmation.",
        "roles": ["automation", "analyst", "admin", "product_manager"],
        "mcp_safe": False,
        "mcp_requires_confirm": True,
    },
    "python_execute": {
        "description": "Execute Python code in a sandboxed subprocess. "
                       "Output is captured and returned.",
        "roles": ["analyst", "automation", "admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "web_search": {
        "description": "Search the web via DuckDuckGo + Bing and return ranked results.",
        "roles": ["researcher", "documentation", "admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "file_editor": {
        "description": "View, create, and edit files in the workspace.",
        "roles": ["researcher", "analyst", "automation", "documentation",
                   "product_manager", "admin"],
        "mcp_safe": False,
        "mcp_requires_confirm": True,
    },
    "powershell": {
        "description": "Execute a PowerShell command directly (Windows only).",
        "roles": ["automation", "admin"],
        "mcp_safe": False,
        "mcp_requires_confirm": True,
    },
    "computer_use": {
        "description": "Control mouse and keyboard for GUI automation.",
        "roles": ["automation"],
        "requires_deps": ["pyautogui"],
        "mcp_safe": False,
        "mcp_requires_confirm": True,
        "is_experimental": True,
    },
    "swarm": {
        "description": "Coordinate multiple sub-agents to solve complex tasks in parallel.",
        "roles": ["researcher", "admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "debate": {
        "description": "Run a multi-agent debate to reach consensus on a question.",
        "roles": ["researcher", "admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "dispatch_parallel_tasks": {
        "description": "Dispatch independent tasks to parallel sub-agents.",
        "roles": ["admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "workflow_orchestrator": {
        "description": "Orchestrate a DAG of dependent tasks across sub-agents.",
        "roles": ["admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "todo_write": {
        "description": "Track task progress with a structured to-do checklist.",
        "roles": ["admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "knowledge": {
        "description": "Query and save structured knowledge notes.",
        "roles": ["researcher", "analyst", "documentation", "product_manager", "admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
    "persistent_memory": {
        "description": "Store and retrieve persistent memories across sessions.",
        "roles": ["admin"],
        "mcp_safe": True,
        "mcp_requires_confirm": False,
    },
}


class ToolDiscoveryAdapter(ToolDiscoveryPort):
    """Discovers tool manifests by introspecting BaseTool subclasses.

    Merges automatic discovery (class-level ``_manifest_*`` attributes) with
    the manual manifest overrides defined above.  Applies role filtering via
    :class:`RoleBasedToolRegistry`.
    """

    def __init__(self, role_registry: Optional[RoleBasedToolRegistry] = None) -> None:
        self._role_registry = role_registry or RoleBasedToolRegistry()

    # ── ToolDiscoveryPort implementation ──────────────────────────────

    async def list_tools(self, role: str | None = None) -> list[ToolManifest]:
        """Return all discoverable tool manifests, optionally filtered by role."""
        manifests: list[ToolManifest] = []

        for tool_cls in self._discover_subclasses():
            manifest = self._build_manifest(tool_cls)
            if manifest is None:
                continue
            manifests.append(manifest)

        # Sort alphabetically
        manifests.sort(key=lambda m: m.name)

        # Role filter
        if role is not None:
            authorized = set(self._role_registry.get_tools_for_role(role))
            manifests = [m for m in manifests if not m.roles or m.name in authorized]

        return manifests

    async def get_tool(self, name: str) -> ToolManifest | None:
        """Return a single tool manifest by name."""
        for manifest in await self.list_tools():
            if manifest.name == name:
                return manifest
        return None

    # ── Internal ──────────────────────────────────────────────────────

    @staticmethod
    def _discover_subclasses() -> list[type[BaseTool]]:
        """Find all concrete BaseTool subclasses (non-abstract, instantiable).

        Imports the ``weebot.tools`` package so that all tool modules are
        loaded before introspection — Python only tracks ``__subclasses__()``
        for classes that have been imported.
        """
        # Ensure tool modules are loaded so __subclasses__() sees them
        _import_tool_modules()

        from weebot.tools.base import BaseTool as BT
        subclasses: list[type[BaseTool]] = []

        def _recurse(cls: type) -> None:
            for sub in cls.__subclasses__():
                # Skip abstract intermediates
                if not getattr(sub, "__abstractmethods__", None):
                    subclasses.append(sub)
                _recurse(sub)

        _recurse(BT)
        return subclasses

    def _build_manifest(self, tool_cls: type[BaseTool]) -> ToolManifest | None:
        """Build a ToolManifest from a BaseTool subclass.

        Instantiate the tool to read its ``name`` attribute (which is set
        per-instance, not at the class level).  For tools that fail to
        instantiate (e.g. missing deps), the manual manifest is still
        checked by class name.

        Precedence: manual manifest > class-level `_manifest_*` attributes > defaults.
        """
        # Try to instantiate to get the name
        try:
            instance = tool_cls()
            name = getattr(instance, "name", "")
        except Exception:
            _log.debug("Failed to instantiate %s for manifest", tool_cls.__name__)
            name = ""

        # Fallback: derive name from class name convention
        if not name:
            # BashTool → bash, WebSearchTool → web_search
            import re
            name = re.sub(r"(?<!^)(?=[A-Z])", "_", tool_cls.__name__).lower()
            if name.endswith("_tool"):
                name = name[:-5]  # strip _tool suffix
            if not name or name == tool_cls.__name__.lower():
                return None

        # Check for manual override
        manual = _MANUAL_MANIFESTS.get(name, {})

        # Try class-level manifest attributes
        description = (
            manual.get("description")
            or getattr(tool_cls, "_manifest_description", "")
            or getattr(tool_cls, "description", "")
        )
        roles = manual.get("roles") or getattr(tool_cls, "_manifest_roles", [])
        requires_deps = (
            manual.get("requires_deps")
            or getattr(tool_cls, "_manifest_requires_deps", [])
        )
        mcp_safe = manual.get(
            "mcp_safe", getattr(tool_cls, "_manifest_mcp_safe", False)
        )
        mcp_requires_confirm = manual.get(
            "mcp_requires_confirm",
            getattr(tool_cls, "_manifest_mcp_requires_confirm", True),
        )
        is_experimental = manual.get(
            "is_experimental", getattr(tool_cls, "_manifest_is_experimental", False)
        )

        return ToolManifest(
            name=name,
            description=description,
            roles=roles,
            requires_deps=requires_deps,
            mcp_safe=mcp_safe,
            mcp_requires_confirm=mcp_requires_confirm,
            is_experimental=is_experimental,
        )
