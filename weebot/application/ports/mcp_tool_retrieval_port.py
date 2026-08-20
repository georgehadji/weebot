"""McpToolRetrievalPort — abstract interface for scoped MCP tool retrieval.

Implementations index external MCP tools and retrieve the top-k most
relevant tools for a given user query.  This allows the agent to see only
a small, query-relevant subset of all bridged MCP tools instead of the
full union, which avoids the accuracy collapse documented in the MCP
High-Probability Enhancement Plan.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.mcp import MCPToolInfo


class McpToolRetrievalPort(ABC):
    """Index MCP tools and retrieve a scoped subset for a query."""

    @abstractmethod
    async def index_tools(self, tools: list[MCPToolInfo]) -> None:
        """Store tools in the retrieval index."""
        ...

    @abstractmethod
    async def retrieve_for_query(self, query: str, k: int = 8) -> list[MCPToolInfo]:
        """Return the top-k most relevant tools for the query."""
        ...
