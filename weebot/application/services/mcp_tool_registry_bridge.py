"""MCPToolRegistryBridge — connects MCP servers to the Weebot ToolRegistry.

On startup and reload, this bridge iterates configured MCP servers,
discovers their tools via MCPClientManager, applies filters, and registers
namespaced tools (``mcp__<server>__<tool>``) into the RoleBasedToolRegistry.

It also handles ``notifications/tools/list_changed`` for dynamic updates
and manages the lifecycle of per-server tool registrations.
"""
from __future__ import annotations

import fnmatch
import logging
from typing import Any

from weebot.domain.models.mcp import MCPServerConfig, MCPToolInfo
from weebot.tools.tool_registry import RoleBasedToolRegistry

logger = logging.getLogger(__name__)

# Namespace prefix for MCP tools to avoid collision with native tools.
# Pattern: mcp__<server_name>__<original_tool_name>
MCP_TOOL_PREFIX = "mcp__"


def _build_namespaced_name(server_name: str, original_name: str) -> str:
    """Build a globally unique, namespaced tool name.

    Pattern: ``mcp__<server>__<tool>``  (double underscore separators)
    Example: ``mcp__stripe__create_payment_intent``
    """
    # Sanitize: replace dots and hyphens that could confuse parsing
    safe_server = server_name.replace(".", "_").replace("-", "_")
    safe_tool = original_name.replace(".", "_").replace("-", "_")
    return f"{MCP_TOOL_PREFIX}{safe_server}__{safe_tool}"


def _parse_namespaced_name(namespaced: str) -> tuple[str, str] | None:
    """Reverse ``_build_namespaced_name``.

    Returns ``(server_name, original_tool_name)`` or ``None`` if
    the name doesn't follow the MCP naming convention.
    """
    if not namespaced.startswith(MCP_TOOL_PREFIX):
        return None
    rest = namespaced[len(MCP_TOOL_PREFIX):]
    parts = rest.split("__", 1)
    if len(parts) != 2:
        return None
    return (parts[0], parts[1])


def _apply_tool_filters(
    server_config: MCPServerConfig,
    tools: list[MCPToolInfo],
) -> list[MCPToolInfo]:
    """Apply include/exclude filters from *server_config* to *tools*.

    - If ``include`` is set, only tools matching at least one include glob pass.
    - If ``exclude`` is set, tools matching any exclude glob are removed.
    - If neither is set, all tools pass.
    """
    filtered = list(tools)

    if server_config.tools.include:
        include_patterns = server_config.tools.include
        filtered = [
            t for t in filtered
            if any(fnmatch.fnmatch(t.original_name, pat) for pat in include_patterns)
        ]

    if server_config.tools.exclude:
        exclude_patterns = server_config.tools.exclude
        filtered = [
            t for t in filtered
            if not any(fnmatch.fnmatch(t.original_name, pat) for pat in exclude_patterns)
        ]

    return filtered


class MCPToolRegistryBridge:
    """Bridges MCP server tools into the Weebot tool registry.

    Usage:
        bridge = MCPToolRegistryBridge(mcp_client, registry)
        await bridge.initialize()
        # Tools are now registered as mcp__<server>__<tool>
        await bridge.reload()
        # Re-discovers and re-registers all tools
        await bridge.close()
        # Unregisters all MCP tools
    """

    def __init__(
        self,
        mcp_client: Any = None,
        registry: Any = None,
    ) -> None:
        self._mcp_client = mcp_client
        self._registry = registry or RoleBasedToolRegistry()
        self._server_configs: dict[str, MCPServerConfig] = {}
        self._registered_tools: dict[str, list[str]] = {}  # server_name -> [namespaced_names]
        self._skill_indexer = None  # MCPToolSkillIndexer, wired by DI

    def set_mcp_client(self, client: Any) -> None:
        """Set or replace the MCP client (useful for DI)."""
        self._mcp_client = client

    def set_server_configs(self, configs: dict[str, MCPServerConfig]) -> None:
        """Set server configurations (useful for DI/testing)."""
        self._server_configs = configs

    def set_skill_indexer(self, indexer) -> None:
        """Wire the MCPToolSkillIndexer for semantic skill indexing (Enhancement 3).

        Args:
            indexer: An ``MCPToolSkillIndexer`` instance, or ``None`` to disable.
        """
        self._skill_indexer = indexer

    async def initialize(self) -> int:
        """Connect to all configured servers and register their tools.

        Returns:
            Number of tools registered.
        """
        if self._mcp_client is None:
            logger.warning("MCP client not set — bridge cannot initialize")
            return 0

        # Ensure MCP client is connected and tools are cached
        # (the MCP client may have already been initialized)
        for server_name, config in self._server_configs.items():
            if not config.enabled:
                continue
            try:
                # The MCPClientManager handles caching internally
                logger.info("Bridge: server %s configured (transport=%s)", server_name, config.transport.value)
            except Exception as exc:
                logger.error("Bridge: failed to configure server %s: %s", server_name, exc)

        # Register all cached tools
        return await self._register_all_tools()

    async def _register_all_tools(self) -> int:
        """Read cached MCP tools, apply filters, and register into the tool registry."""
        if self._mcp_client is None:
            return 0

        total = 0
        try:
            # Get all tools from the MCP client (cached)
            raw_tools = await self._mcp_client.get_all_tools()
        except Exception as exc:
            logger.warning("Bridge: failed to get MCP tools: %s", exc)
            raw_tools = []

        # Group raw tools by server name
        server_tools: dict[str, list[MCPToolInfo]] = {}
        for raw in raw_tools:
            func = raw.get("function", raw)
            namespaced = func.get("name", "")

            parsed = _parse_namespaced_name(namespaced)
            if parsed is None:
                continue

            server_name, original_name = parsed
            if server_name not in server_tools:
                server_tools[server_name] = []

            server_tools[server_name].append(MCPToolInfo(
                original_name=original_name,
                namespaced_name=namespaced,
                description=func.get("description", ""),
                input_schema=func.get("parameters", {}),
                server_name=server_name,
            ))

        # Apply per-server filters and register
        for server_name, config in self._server_configs.items():
            if not config.enabled:
                continue

            raw_for_server = server_tools.get(server_name, [])
            filtered = _apply_tool_filters(config, raw_for_server)
            registered_names: list[str] = []

            for tool_info in filtered:
                self._register_single_tool(server_name, tool_info)
                registered_names.append(tool_info.namespaced_name)

            self._registered_tools[server_name] = registered_names
            total += len(registered_names)
            logger.info(
                "Bridge: registered %d tools from MCP server '%s' (%d filtered out)",
                len(registered_names), server_name,
                len(raw_for_server) - len(registered_names),
            )

            # Enhancement 3: index MCP tools into the skill registry
            if self._skill_indexer is not None:
                await self._skill_indexer.index_tool_infos(filtered, server_name)

        return total

    def _register_single_tool(self, server_name: str, tool_info: MCPToolInfo) -> None:
        """Register a single MCP tool into the tool registry.

        Write tools (matching ``write_tools`` patterns on the server config)
        are registered to **admin-only** at **restricted** tier.  Read tools
        register to all four roles at **controlled** tier.
        """
        namespaced = tool_info.namespaced_name

        # Check if this tool matches any write-tool patterns
        config = self._server_configs.get(server_name)
        write_patterns = config.tools.write_tools if config and config.tools.write_tools else []
        is_write = any(fnmatch.fnmatch(tool_info.original_name, p) for p in write_patterns)

        if is_write:
            # Write tools: admin-only + restricted tier
            roles = ["admin"]
            tier = "restricted"
        else:
            # Read tools: all roles + controlled tier
            roles = ["admin", "automation", "researcher", "coder"]
            tier = "controlled"

        for role in roles:
            try:
                self._registry.add_tool_to_role(role, namespaced)
            except ValueError:
                # Role doesn't exist yet — create it
                self._registry.add_role(role, [namespaced])

        # Set tier
        if self._registry.get_tool_tier(namespaced) == "public":
            self._registry.set_tool_tier(namespaced, tier)

        logger.debug(
            "Bridge: registered MCP tool %s (server: %s, write=%s, tier=%s)",
            namespaced, server_name, is_write, tier,
        )

    async def reload(self) -> int:
        """Re-discover and re-register all MCP tools.

        This can be called at runtime (e.g., via /reload-mcp slash command)
        to pick up new tools without restarting.

        Returns:
            Number of tools registered after reload.
        """
        # Unregister existing tools first
        await self.unregister_all_server_tools()

        # Clear and re-fetch from MCP client
        if self._mcp_client is not None:
            try:
                await self._mcp_client.cleanup()
                await self._mcp_client.initialize()
            except Exception as exc:
                logger.warning("Bridge: MCP client re-init failed during reload: %s", exc)

        return await self._register_all_tools()

    async def unregister_server_tools(self, server_name: str) -> int:
        """Remove all tools belonging to a specific MCP server.

        Returns:
            Number of tools unregistered.
        """
        registered = self._registered_tools.pop(server_name, [])
        for namespaced in registered:
            for role in list(self._registry.list_roles()):
                try:
                    self._registry.remove_tool_from_role(role, namespaced)
                except (ValueError, KeyError):
                    pass
        logger.info("Bridge: unregistered %d tools from server '%s'", len(registered), server_name)
        return len(registered)

    async def unregister_all_server_tools(self) -> int:
        """Remove all MCP tools from the registry.

        Returns:
            Number of tools unregistered.
        """
        total = 0
        for server_name in list(self._registered_tools.keys()):
            total += await self.unregister_server_tools(server_name)
        return total

    async def close(self) -> None:
        """Clean shutdown — unregister all tools and disconnect clients."""
        await self.unregister_all_server_tools()
        if self._mcp_client is not None:
            await self._mcp_client.cleanup()
        logger.info("MCPToolRegistryBridge closed")

    def get_registered_tools(self) -> dict[str, list[str]]:
        """Get current registration state: server_name -> [namespaced_tool_names]."""
        return dict(self._registered_tools)

    def get_stats(self) -> dict[str, Any]:
        """Return statistics about the current bridge state."""
        total_tools = sum(len(tools) for tools in self._registered_tools.values())
        return {
            "servers": len(self._registered_tools),
            "total_tools": total_tools,
            "per_server": {
                srv: len(tools) for srv, tools in self._registered_tools.items()
            },
        }
