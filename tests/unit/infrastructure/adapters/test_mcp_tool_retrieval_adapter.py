"""Unit tests for LocalEmbeddingMcpToolRetrievalAdapter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from weebot.domain.models.mcp import MCPToolInfo
from weebot.infrastructure.adapters.mcp_tool_retrieval_adapter import (
    LocalEmbeddingMcpToolRetrievalAdapter,
    _cosine_similarity,
)


@dataclass
class _EmbeddingResult:
    """Stub result returned by a fake embeddings object."""

    embedding: List[float]


class _FakeEmbeddings:
    """Deterministic embeddings stub: each document maps to a unique vector."""

    # Fixed vector dimension used for both documents and queries so cosine
    # similarity is always defined regardless of corpus size.
    DIM: int = 8

    def __init__(self) -> None:
        self._index_calls: List[List[str]] = []
        self._query_calls: List[str] = []

    async def embed_documents(self, texts: List[str]) -> List[_EmbeddingResult]:
        self._index_calls.append(list(texts))
        # Deterministic one-hot-ish vectors: position i is hot for doc i.
        results = []
        for i, text in enumerate(texts):
            vec = [0.0] * self.DIM
            vec[i % self.DIM] = 1.0
            results.append(_EmbeddingResult(embedding=vec))
        return results

    async def embed_query(self, query: str) -> _EmbeddingResult:
        self._query_calls.append(query)
        # Query vector aligned with the first document dimension.
        vec = [0.0] * self.DIM
        vec[0] = 1.0
        return _EmbeddingResult(embedding=vec)


class TestCosineSimilarity:
    """Basic vector similarity math."""

    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_different_length_raises(self):
        with pytest.raises(ValueError):
            _cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


class TestLocalEmbeddingMcpToolRetrievalAdapter:
    """Adapter indexing and retrieval with mocked embeddings."""

    @staticmethod
    def _make_tool(name: str, description: str) -> MCPToolInfo:
        return MCPToolInfo(
            original_name=name,
            namespaced_name=f"mcp__srv__{name}",
            description=description,
            input_schema={},
            server_name="srv",
        )

    @pytest.mark.asyncio
    async def test_indexes_tools(self):
        embeddings = _FakeEmbeddings()
        adapter = LocalEmbeddingMcpToolRetrievalAdapter(embeddings=embeddings)
        tools = [
            self._make_tool("get_weather", "Get weather"),
            self._make_tool("send_email", "Send email"),
        ]

        await adapter.index_tools(tools)

        assert len(adapter._index) == 2
        assert embeddings._index_calls == [["Get weather", "Send email"]]

    @pytest.mark.asyncio
    async def test_retrieve_top_k(self):
        embeddings = _FakeEmbeddings()
        adapter = LocalEmbeddingMcpToolRetrievalAdapter(embeddings=embeddings)
        tools = [
            self._make_tool("a", "weather alpha"),
            self._make_tool("b", "email beta"),
            self._make_tool("c", "weather gamma"),
        ]
        await adapter.index_tools(tools)

        # Query vector is [1, 0, 0] so first tool is most similar.
        results = await adapter.retrieve_for_query("anything", k=2)

        assert len(results) == 2
        assert results[0].original_name == "a"

    @pytest.mark.asyncio
    async def test_retrieve_without_index_returns_empty(self):
        embeddings = _FakeEmbeddings()
        adapter = LocalEmbeddingMcpToolRetrievalAdapter(embeddings=embeddings)

        results = await adapter.retrieve_for_query("weather", k=8)

        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_preserves_input_schema_in_metadata(self):
        embeddings = _FakeEmbeddings()
        adapter = LocalEmbeddingMcpToolRetrievalAdapter(embeddings=embeddings)
        schema = {"type": "object", "properties": {"city": {"type": "string"}}}
        tools = [
            MCPToolInfo(
                original_name="get_weather",
                namespaced_name="mcp__srv__get_weather",
                description="Get weather",
                input_schema=schema,
                server_name="srv",
            )
        ]
        await adapter.index_tools(tools)

        results = await adapter.retrieve_for_query("weather", k=8)

        assert len(results) == 1
        assert results[0].input_schema == schema
