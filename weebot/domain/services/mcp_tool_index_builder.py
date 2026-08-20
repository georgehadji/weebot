"""Pure, testable builder for the MCP tool catalog index."""

from __future__ import annotations


from weebot.domain.models.mcp import MCPToolInfo
from weebot.domain.models.mcp_catalog import MCPToolCatalogIndex


def build_index(
    tools: list[MCPToolInfo], embeddings: list[list[float]] | None = None
) -> list[MCPToolCatalogIndex]:
    """Build a searchable catalog index from tool metadata and embeddings.

    Args:
        tools: List of MCP tool metadata.
        embeddings: Optional parallel list of description embeddings.  When
            omitted, embeddings are left unset for later lazy computation.

    Returns:
        List of ``MCPToolCatalogIndex`` entries, one per tool.

    Raises:
        ValueError: If *embeddings* is provided but its length does not match
            the number of tools.
    """
    if embeddings is not None and len(embeddings) != len(tools):
        raise ValueError(
            f"tools ({len(tools)}) and embeddings ({len(embeddings)}) must have the same length"
        )

    indexed: list[MCPToolCatalogIndex] = []
    for i, tool in enumerate(tools):
        indexed.append(
            MCPToolCatalogIndex(
                original_name=tool.original_name,
                namespaced_name=tool.namespaced_name,
                description=tool.description,
                server_name=tool.server_name,
                embedding=embeddings[i] if embeddings is not None else None,
                metadata={"input_schema": tool.input_schema},
            )
        )
    return indexed
