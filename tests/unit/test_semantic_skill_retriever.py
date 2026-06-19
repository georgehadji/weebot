"""Unit tests for SemanticSkillRetriever.

Covers:
- Index building at refresh() time
- retrieve() ordering by cosine similarity
- Empty registry / empty text edge cases
- Lazy index initialization on first retrieve()
- Integration with the SkillMatch return contract
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from weebot.domain.models.skill import Skill, SkillMatch
from weebot.application.ports.vector_store_port import VectorStorePort


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_registry():
    """Return a SkillRegistry pre-loaded with test skills."""
    from weebot.application.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry._skills = {
        "web_research": Skill(
            name="web_research",
            description="Web search and information gathering",
            content="Use web_search and browser tools to find information.",
        ),
        "architecture_design": Skill(
            name="architecture_design",
            description="System architecture and design patterns",
            content="Design system architecture following Clean Architecture.",
        ),
        "tdd_app_dev": Skill(
            name="tdd_app_dev",
            description="Test-driven development workflow",
            content="RED -> GREEN -> CLEAN cycle for app development.",
        ),
    }
    return registry


@pytest.fixture
def mock_empty_registry():
    """Return a SkillRegistry with no skills loaded."""
    from weebot.application.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry._skills = {}
    return registry


@pytest.fixture
def mock_store():
    """Return an AsyncMock VectorStorePort with controlled query results."""
    store = MagicMock(spec=VectorStorePort)
    store.upsert = AsyncMock()
    store.query = AsyncMock()
    store.count = AsyncMock(return_value=3)
    return store


@pytest.fixture
def mock_embeddings():
    """Return a MagicMock LocalEmbeddings with dynamic vector responses.

    Builds distinguishable 384-dim unit vectors for N documents on the fly.
    Doc i gets a vector with baseline 0.3 in all dims + 1.0 in dim (i * 10).
    Query classification maps keywords to dimension indices.
    """
    emb = MagicMock()

    async def embed_documents(docs, titles=None):
        n = len(docs)
        vecs = np.full((n, 384), 0.3, dtype=np.float32)
        for i in range(n):
            vecs[i, i * 10] = 1.0
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        return [MagicMock(embedding=vecs[i].tolist()) for i in range(n)]

    async def embed_query(query):
        if "search" in query.lower() or "find" in query.lower():
            dim = 0
        elif "design" in query.lower() or "architecture" in query.lower():
            dim = 10
        else:
            dim = 20
        qvec = np.full(384, 0.3, dtype=np.float32)
        qvec[dim] = 1.0
        return MagicMock(embedding=qvec.tolist())

    emb.embed_documents = embed_documents
    emb.embed_query = embed_query
    return emb


# ── Tests ────────────────────────────────────────────────────────────


class TestSemanticSkillRetriever:
    """Core retriever behavior."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_sorted_by_relevance(
        self, mock_registry, mock_store, mock_embeddings
    ):
        """retrieve() returns skills ordered by cosine similarity."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        # Wire the mock store to return controlled results
        mock_store.query = AsyncMock(return_value=[
            ("web_research", 0.95, {"description": "", "preview": ""}),
            ("architecture_design", 0.80, {"description": "", "preview": ""}),
        ])

        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)
        await retriever.refresh()

        results = await retriever.retrieve("search the web for information", top_k=2)

        assert len(results) == 2
        assert results[0].skill_name == "web_research"
        assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_retrieve_returns_different_ordering_for_different_queries(
        self, mock_registry, mock_store, mock_embeddings
    ):
        """Different queries produce different top-1 results."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        mock_store.query = AsyncMock()
        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)
        await retriever.refresh()

        # First query returns web_research on top
        mock_store.query.return_value = [
            ("web_research", 0.95, {}),
            ("architecture_design", 0.80, {}),
            ("tdd_app_dev", 0.30, {}),
        ]
        search_result = await retriever.retrieve("search the web")

        # Second query returns architecture_design on top
        mock_store.query.return_value = [
            ("architecture_design", 0.95, {}),
            ("web_research", 0.80, {}),
            ("tdd_app_dev", 0.30, {}),
        ]
        design_result = await retriever.retrieve("system architecture design")

        assert search_result[0].skill_name == "web_research"
        assert design_result[0].skill_name == "architecture_design"

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty(
        self, mock_empty_registry, mock_store, mock_embeddings
    ):
        """An empty skill registry returns empty results."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        retriever = SemanticSkillRetriever(mock_empty_registry, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)
        await retriever.refresh()

        results = await retriever.retrieve("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_lazy_index_build_on_first_retrieve(
        self, mock_registry, mock_store, mock_embeddings
    ):
        """Index is built lazily on first retrieve() if refresh() wasn't called."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        mock_store.query = AsyncMock(return_value=[
            ("web_research", 0.95, {}),
        ])

        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)
        assert retriever._index_built is False

        results = await retriever.retrieve("search the web", top_k=1)

        assert len(results) == 1
        assert retriever._index_built is True

    @pytest.mark.asyncio
    async def test_retrieve_respects_top_k(
        self, mock_registry, mock_store, mock_embeddings
    ):
        """retrieve() returns exactly top_k results."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        mock_store.query = AsyncMock()
        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)
        await retriever.refresh()

        mock_store.query.return_value = [("web_research", 0.95, {})]
        results = await retriever.retrieve("search", top_k=1)
        assert len(results) == 1

        mock_store.query.return_value = [
            ("web_research", 0.95, {}),
            ("architecture_design", 0.80, {}),
            ("tdd_app_dev", 0.30, {}),
        ]
        results = await retriever.retrieve("search", top_k=5)
        assert len(results) == 3  # only 3 skills exist

    @pytest.mark.asyncio
    async def test_refresh_rebuilds_index(
        self, mock_registry, mock_store, mock_embeddings
    ):
        """Calling refresh() twice is safe and rebuilds the index."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)

        await retriever.refresh()
        assert retriever._index_built is True

        # Modify registry
        mock_registry._skills["new_skill"] = Skill(
            name="new_skill",
            description="A new skill",
            content="New skill content",
        )
        await retriever.refresh()
        assert retriever._index_built is True

    @pytest.mark.asyncio
    async def test_skillmatch_contract(
        self, mock_registry, mock_store, mock_embeddings
    ):
        """Returned SkillMatch objects conform to the contract."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        mock_store.query = AsyncMock(return_value=[
            ("web_research", 0.95, {"description": "Web search", "preview": "preview"}),
            ("architecture_design", 0.80, {"description": "Arch", "preview": "preview2"}),
        ])

        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)
        await retriever.refresh()

        results = await retriever.retrieve("search", top_k=2)
        for r in results:
            assert isinstance(r, SkillMatch)
            assert isinstance(r.skill_name, str) and r.skill_name
            assert isinstance(r.description, str)
            assert isinstance(r.content_preview, str)
            assert 0.0 <= r.score <= 1.0

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_empty(
        self, mock_registry, mock_store
    ):
        """If embedding fails, retrieve() returns empty list gracefully."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)

        # Mock a failing embed_query after a successful refresh
        bad_embeddings = MagicMock()
        bad_embeddings.embed_query = AsyncMock(side_effect=RuntimeError("model crashed"))

        # refresh must succeed to build the index
        good_embeddings = MagicMock()
        good_embeddings.embed_documents = AsyncMock(return_value=[
            MagicMock(embedding=np.zeros(384).tolist())
            for _ in range(3)
        ])
        retriever._get_embeddings = MagicMock(return_value=good_embeddings)
        await retriever.refresh()

        # Now swap to failing embeddings for query
        retriever._get_embeddings = MagicMock(return_value=bad_embeddings)

        results = await retriever.retrieve("anything")
        assert results == []


class TestSemanticSkillRetrieverEdgeCases:
    """Edge case behaviors."""

    @pytest.mark.asyncio
    async def test_zero_vector_guard(
        self, mock_registry, mock_store
    ):
        """Zero-vector skills are handled gracefully (norm clamped to 1.0)."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        # After refresh, query delegates to store
        mock_store.query = AsyncMock(return_value=[
            ("some_skill", 0.85, {"description": "", "preview": ""}),
        ])

        retriever = SemanticSkillRetriever(mock_registry, store=mock_store)

        # Return a mix of zero and normal vectors for encoding
        zero_embeddings = MagicMock()
        skill_count = len(mock_registry.list_all())
        norm_vec = np.zeros(384, dtype=np.float32)
        norm_vec[0] = 1.0
        norm_vec = norm_vec / np.linalg.norm(norm_vec)

        async def embed_docs(docs, titles=None):
            results = []
            for i in range(len(docs)):
                if i == 0:
                    results.append(MagicMock(embedding=np.zeros(384).tolist()))
                else:
                    results.append(MagicMock(embedding=norm_vec.tolist()))
            return results

        async def embed_query(query):
            q = np.zeros(384, dtype=np.float32)
            q[0] = 1.0
            return MagicMock(embedding=(q / np.linalg.norm(q)).tolist())

        zero_embeddings.embed_documents = embed_docs
        zero_embeddings.embed_query = embed_query
        retriever._get_embeddings = MagicMock(return_value=zero_embeddings)
        await retriever.refresh()

        results = await retriever.retrieve("test query", top_k=skill_count)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_refresh_on_empty_registry(self, mock_empty_registry, mock_store):
        """refresh() on an empty registry sets index_built=False cleanly."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        retriever = SemanticSkillRetriever(mock_empty_registry, store=mock_store)
        await retriever.refresh()
        assert retriever._index_built is False

    @pytest.mark.asyncio
    async def test_retrieve_negative_top_k_uses_default(
        self, mock_registry, mock_store, mock_embeddings
    ):
        """Negative top_k falls back to the instance default."""
        from weebot.application.services.semantic_skill_retriever import (
            SemanticSkillRetriever,
        )

        mock_store.query = AsyncMock(return_value=[
            ("web_research", 0.95, {}),
            ("architecture_design", 0.80, {}),
        ])

        retriever = SemanticSkillRetriever(mock_registry, top_k=2, store=mock_store)
        retriever._get_embeddings = MagicMock(return_value=mock_embeddings)
        await retriever.refresh()

        results = await retriever.retrieve("search", top_k=0)
        assert len(results) == 2  # falls back to top_k=2 from __init__
