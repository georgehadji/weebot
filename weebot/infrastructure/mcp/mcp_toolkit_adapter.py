"""Adapter that exposes MCP tools as Weebot BaseTool instances."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from weebot.infrastructure.mcp.mcp_client_manager import MCPClientManager
from weebot.tools.base import BaseTool, ToolResult


class MCPToolAdapter(BaseTool):
    """Wraps a single MCP tool as a Weebot BaseTool."""

    def __init__(self, name: str, description: str, parameters: Dict[str, Any], manager: MCPClientManager):
        super().__init__(
            name=name,
            description=description,
            parameters=parameters,
        )
        self._manager = manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self._manager.call_tool(self.name, kwargs)
            return ToolResult(output=result, success=True)
        except Exception as exc:
            return ToolResult(error=str(exc), success=False)


class MCPToolkitAdapter:
    """Facades MCPClientManager into a list of Weebot BaseTools."""

    def __init__(self, manager: Optional[MCPClientManager] = None):
        self._manager = manager or MCPClientManager()
        self._tools: List[BaseTool] = []

    async def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        if config:
            self._manager = MCPClientManager(config)
        await self._manager.initialize()
        mcp_tools = await self._manager.get_all_tools()
        self._tools = []
        for spec in mcp_tools:
            func = spec["function"]
            self._tools.append(
                MCPToolAdapter(
                    name=func["name"],
                    description=func["description"],
                    parameters=func["parameters"],
                    manager=self._manager,
                )
            )

    def get_tools(self) -> List[BaseTool]:
        return list(self._tools)

    async def cleanup(self) -> None:
        await self._manager.cleanup()
        self._tools = []
