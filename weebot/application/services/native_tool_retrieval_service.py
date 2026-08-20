"""NativeToolRetrievalService — semantic selection of native Weebot tools.

Gated by ``mcp_scope_native_tools``; when enabled, PlanActFlow scopes the
native tool set alongside external MCP tools so the total per-turn tool count
stays within budget.
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.domain.models.mcp import MCPToolInfo
from weebot.tools.tool_registry import RoleBasedToolRegistry

logger = logging.getLogger(__name__)


class NativeToolRetrievalService:
    """Indexes native Weebot tools and retrieves the top-k relevant ones.

    Native tools are represented as :class:`MCPToolInfo` with ``server_name``
    set to ``"native"`` so the same local-embedding adapter used for external
    MCP tools can be reused.

    The concrete retrieval adapter is injected from outside this module so the
    Application layer does not depend directly on Infrastructure.
    """

    def __init__(
        self, registry: RoleBasedToolRegistry, retrieval_adapter: Any = None, k: int = 4
    ) -> None:
        self._registry = registry
        self._k = k
        self._adapter = retrieval_adapter
        self._indexed_names: set[str] = set()

    def set_adapter(self, adapter: Any) -> None:
        """Inject the retrieval adapter after construction."""
        self._adapter = adapter

    async def initialize(self) -> None:
        """Index all native tools discoverable through the registry."""
        if self._adapter is None:
            logger.debug("NativeToolRetrievalService: no adapter injected, skipping index")
            return

        tool_infos = self._build_native_tool_infos()
        if not tool_infos:
            logger.warning("NativeToolRetrievalService: no native tools to index")
            return

        await self._adapter.index_tools(tool_infos)
        self._indexed_names = {info.namespaced_name for info in tool_infos}
        logger.info("Indexed %d native tools for scoped retrieval", len(tool_infos))

    def _build_native_tool_infos(self) -> list[MCPToolInfo]:
        """Build MCPToolInfo objects for native tools in the registry."""
        class_map = self._registry.build_tool_class_map()
        infos: list[MCPToolInfo] = []
        for name, tool_cls in class_map.items():
            description = ""
            try:
                instance = tool_cls()
                description = getattr(instance, "description", "") or ""
            except Exception as exc:
                logger.debug("Native tool %s instantiation skipped: %s", name, exc)
                description = getattr(tool_cls, "description", "") or ""

            infos.append(
                MCPToolInfo(
                    original_name=name,
                    namespaced_name=name,
                    description=description or name,
                    input_schema=getattr(tool_cls, "parameters", {}),
                    server_name="native",
                )
            )
        return infos

    async def select_for_query(self, query: str) -> list[str]:
        """Return the top-k native tool names relevant to *query*.

        Lazily initializes the index on first call so callers do not need to
        await a separate initialization step.  Returns an empty list when no
        adapter has been injected.
        """
        if self._adapter is None:
            return []

        if not self._indexed_names:
            await self.initialize()

        if not self._indexed_names:
            return []

        relevant = await self._adapter.retrieve_for_query(query, k=self._k)
        return [tool.namespaced_name for tool in relevant]

    def is_indexed(self, name: str) -> bool:
        """Return True if *name* was indexed as a native tool."""
        return name in self._indexed_names
