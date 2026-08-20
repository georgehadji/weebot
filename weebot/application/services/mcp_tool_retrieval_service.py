"""McpToolRetrievalService — orchestrates scoped tool retrieval for MCP-bridged tools.

This Application-layer service coordinates the retrieval port (semantic search)
and the registration port (role-based registry mutations) so that only the
most relevant external MCP tools are visible to the agent for a given turn.
"""

from __future__ import annotations

import contextlib
import logging

from weebot.application.ports.mcp_tool_registration_port import McpToolRegistrationPort
from weebot.application.ports.mcp_tool_retrieval_port import McpToolRetrievalPort
from weebot.domain.models.mcp import MCPToolInfo

logger = logging.getLogger(__name__)


class McpToolRetrievalService:
    """Orchestrates scoped tool retrieval for MCP-bridged external servers."""

    def __init__(
        self,
        retrieval_port: McpToolRetrievalPort,
        registration_port: McpToolRegistrationPort,
        k: int = 8,
    ) -> None:
        self._retrieval = retrieval_port
        self._registration = registration_port
        self._k = k
        self._all_tools: list[MCPToolInfo] = []

    async def index_all_tools(self, tools: list[MCPToolInfo]) -> None:
        """Index the full set of external MCP tools for later retrieval."""
        self._all_tools = list(tools)
        await self._retrieval.index_tools(tools)
        logger.info("Indexed %d MCP tools for scoped retrieval", len(tools))

    async def retrieve_for_query(self, query: str, k: int | None = None) -> list[MCPToolInfo]:
        """Return the top-k relevant tools for *query* without mutating the registry.

        Delegates to the configured retrieval port so callers such as
        ``MCPToolRegistryBridge.select_for_query`` can scope tools without
        side effects.
        """
        return await self._retrieval.retrieve_for_query(query, k=k or self._k)

    async def scope_for_query(self, query: str) -> list[MCPToolInfo]:
        """Retrieve top-k relevant tools for *query* and sync them into the registry.

        The previous scoped subset is removed from all roles before the new
        subset is added.  Role-specific filtering still happens elsewhere; this
        service merely ensures that only the retrieved tools are present in the
        registry's role mappings.
        """
        relevant = await self._retrieval.retrieve_for_query(query, k=self._k)

        # Clear previously scoped tools from all roles.
        for role in self._registration.list_roles():
            for tool in self._all_tools:
                with contextlib.suppress(ValueError):
                    self._registration.remove_tool_from_role(role, tool.namespaced_name)

        # Add the newly relevant tools to all roles.
        for tool in relevant:
            for role in self._registration.list_roles():
                try:
                    self._registration.add_tool_to_role(role, tool.namespaced_name)
                except ValueError:
                    # Role may have been removed concurrently; log and continue.
                    logger.debug(
                        "Could not add %s to role %s during scoping", tool.namespaced_name, role
                    )

        logger.info("MCP scoped retrieval: %d tools selected for query %r", len(relevant), query)
        return relevant
