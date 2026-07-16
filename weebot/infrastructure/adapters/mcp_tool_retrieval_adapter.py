"""Local-embedding retrieval adapter for MCP-bridged external tools."""
from __future__ import annotations

import math
from typing import Any

from weebot.application.ports.mcp_tool_retrieval_port import McpToolRetrievalPort
from weebot.domain.models.mcp import MCPToolInfo
from weebot.domain.models.mcp_catalog import MCPToolCatalogIndex


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity between two equal-length vectors."""
    if len(a) != len(b):
        raise ValueError("vectors must have the same length")

    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class LocalEmbeddingMcpToolRetrievalAdapter(McpToolRetrievalPort):
    """Retrieval adapter using weebot's local embeddings (all-MiniLM-L6-v2 fallback).

    Embeds tool descriptions at index time and performs cosine-similarity
    top-k retrieval against an embedded query at request time.
    """

    def __init__(self, embeddings: Any | None = None) -> None:
        self._embeddings = embeddings
        self._index: list[MCPToolCatalogIndex] = []

    async def index_tools(self, tools: list[MCPToolInfo]) -> None:
        from weebot.domain.services.mcp_tool_index_builder import build_index
        from weebot.qmd_integration.embeddings import get_local_embeddings

        emb = self._embeddings or get_local_embeddings()
        descriptions = [t.description for t in tools]
        results = await emb.embed_documents(descriptions)
        vectors = [r.embedding for r in results]
        self._index = build_index(tools, embeddings=vectors)

    async def retrieve_for_query(self, query: str, k: int = 8) -> list[MCPToolInfo]:
        if not self._index:
            return []

        from weebot.qmd_integration.embeddings import get_local_embeddings

        emb = self._embeddings or get_local_embeddings()
        query_result = await emb.embed_query(query)
        query_vec = query_result.embedding

        scored: list[tuple[float, MCPToolCatalogIndex]] = []
        for idx in self._index:
            if idx.embedding is None:
                continue
            sim = _cosine_similarity(query_vec, idx.embedding)
            scored.append((sim, idx))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            MCPToolInfo(
                original_name=idx.original_name,
                namespaced_name=idx.namespaced_name,
                description=idx.description,
                input_schema=idx.metadata.get("input_schema", {}),
                server_name=idx.server_name,
            )
            for _, idx in scored[:k]
        ]
