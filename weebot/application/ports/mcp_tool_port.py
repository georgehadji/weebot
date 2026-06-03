"""MCPToolPort — consumes tools from external MCP servers (Enhancement 3).

MCP (Model Context Protocol) allows weebot to discover and call tools from
external servers.  This port abstracts the transport layer — stdio, SSE,
and streamable-http are handled by the infrastructure adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.tools.base import BaseTool, ToolResult


class MCPToolPort(ABC):
    """Discovers tools from an MCP server and wraps them as BaseTool instances."""

    @abstractmethod
    async def get_tools(self) -> list[BaseTool]:
        """Return all tools exposed by the connected MCP server.

        Each tool is wrapped as a BaseTool that forwards execute() calls
        through the MCP protocol.
        """
        ...

    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool with the given arguments.

        Returns the tool output as a string.
        Raises RuntimeError on connection or execution failure.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Disconnect from the MCP server and clean up."""
        ...
