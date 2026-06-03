"""MCPToolBridge — wraps external MCP server tools as BaseTool instances (Enhancement 3).

Uses the existing MCPClientManager to establish connections, then wraps
every discovered tool in a lightweight BaseTool subclass that delegates
execute() calls through the MCP protocol.

Usage:
    bridge = MCPToolBridge(config)
    await bridge.initialize()
    tools = await bridge.get_tools()  # Returns list[BaseTool]
    tc = ToolCollection(*tools)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.application.ports.mcp_tool_port import MCPToolPort
from weebot.infrastructure.mcp.mcp_client_manager import MCPClientManager
from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class _MCPToolWrapper(BaseTool):
    """Wraps a single MCP tool as a weebot BaseTool.

    Created dynamically by MCPToolBridge._wrap_tool().
    Not meant to be instantiated directly.
    """

    name: str = ""
    description: str = ""
    parameters: dict = {}
    _bridge: Any = None
    _mcp_tool_name: str = ""

    def model_post_init(self, __context: Any) -> None:
        pass  # Skip Pydantic validation for dynamic fields

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self._bridge.call_tool(self._mcp_tool_name, kwargs)
            return ToolResult.success_result(output=str(result))
        except Exception as exc:
            return ToolResult.error_result(
                error=f"MCP tool '{self._mcp_tool_name}' failed: {exc}",
                output="",
            )


class MCPToolBridge(MCPToolPort):
    """Bridge between MCPClientManager and weebot's tool system.

    Args:
        mcp_config: MCP server configuration dict (same format as
                    weebot.config's mcpServers).
    """

    def __init__(self, mcp_config: Optional[dict] = None) -> None:
        self._mcp_config = mcp_config or {}
        self._client: Optional[MCPClientManager] = None
        self._tools: list[BaseTool] = []

    async def initialize(self) -> None:
        """Connect to MCP servers and discover tools."""
        if not self._mcp_config.get("mcpServers"):
            logger.info("No MCP servers configured — bridge idle")
            return

        self._client = MCPClientManager(config=self._mcp_config)
        try:
            await self._client.initialize()
        except Exception as exc:
            logger.warning("MCP bridge initialization failed: %s", exc)
            self._tools = []
            return

        # Discover and wrap tools
        mcp_tool_specs = await self._client.get_all_tools()
        for spec in mcp_tool_specs:
            tool = self._wrap_tool(spec)
            self._tools.append(tool)

        logger.info("MCP bridge: %d tools from %d server(s)", len(self._tools),
                     len(self._mcp_config.get("mcpServers", {})))

    @staticmethod
    def _wrap_tool(spec: dict) -> BaseTool:
        """Convert an MCP tool spec to a BaseTool wrapper."""
        func = spec.get("function", spec)
        name = func.get("name", "unknown")
        description = func.get("description", f"MCP tool: {name}")

        mcp_tool_name = name
        # Strip server prefix to get original tool name
        if "_" in name:
            parts = name.split("_", 1)
            if len(parts) == 2:
                mcp_tool_name = parts[1]

        parameters = func.get("parameters", {"type": "object", "properties": {}})

        wrapper = _MCPToolWrapper(
            name=name,
            description=description,
            parameters=parameters,
        )
        wrapper._bridge = None  # Will be set after creation
        wrapper._mcp_tool_name = mcp_tool_name
        return wrapper

    async def get_tools(self) -> list[BaseTool]:
        """Return all wrapped MCP tools."""
        # Set bridge reference now (avoids circular ref in __init__)
        for t in self._tools:
            t._bridge = self  # type: ignore[attr-defined]
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if self._client is None:
            raise RuntimeError("MCP bridge not initialized")
        return await self._client.call_tool(tool_name, arguments)

    async def close(self) -> None:
        if self._client:
            await self._client.cleanup()
            self._client = None
            self._tools = []

    async def __aenter__(self) -> "MCPToolBridge":
        await self.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
