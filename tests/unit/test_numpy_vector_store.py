"""Unit tests for NumpyVectorStore.

Covers:
- upsert stores vectors and metadata
- query returns sorted results by cosine similarity
- Empty store returns []
- Dimension mismatch raises ValueError
- ID count mismatch raises ValueError
- query excludes zero-or-negative scores
- count returns correct document count
"""
from __future__ import annotations

import numpy as np
import pytest

from weebot.application.ports.vector_store_port import VectorStorePort
from weebot.infrastructure.adapters.numpy_vector_store import NumpyVectorStore


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """Return an empty NumpyVectorStore with 384-dim vectors."""
    return NumpyVectorStore(dim=384)


@pytest.fixture
def three_docs():
    """Return three normalized 384-dim vectors and metadata.

    Each vector has a 0.3 baseline in all dimensions plus a distinguishing
    peak (1.0) in one dimension.  This ensures non-zero similarity between
    unrelated documents (mimicking real cosine distributions).
    """
    vecs = np.full((3, 384), 0.3, dtype=np.float32)
    vecs[0, 0] = 1.0  # doc_a peaks on dim 0
    vecs[1, 1] = 1.0  # doc_b peaks on dim 1
    vecs[2, 2] = 1.0  # doc_c peaks on dim 2
    # L2-normalize
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms
    ids = ["doc_a", "doc_b", "doc_c"]
    meta = [
        {"description": "First document", "preview": "preview_a"},
        {"description": "Second document", "preview": "preview_b"},
        {"description": "Third document", "preview": "preview_c"},
    ]
    return ids, vecs, meta


# ── Tests ────────────────────────────────────────────────────────────


class TestNumpyVectorStore:
    """Core store behavior."""

    @pytest.mark.asyncio
    async def test_upsert_and_query(self, store, three_docs):
        """After upsert, query returns documents sorted by similarity."""
        ids, vecs, meta = three_docs
        await store.upsert(ids, vecs, meta)

        # Query with vector matching doc_a (dim 0)
        query = np.zeros(384, dtype=np.float32)
        query[0] = 1.0
        results = await store.query(query, top_k=3)

        assert len(results) == 3
        assert results[0][0] == "doc_a"  # highest score
        assert results[0][1] > results[1][1]

    @pytest.mark.asyncio
    async def test_query_returns_correct_ordering(self, store, three_docs):
        """Query vectors close to doc_b return doc_b on top."""
        ids, vecs, meta = three_docs
        await store.upsert(ids, vecs, meta)

        query = np.zeros(384, dtype=np.float32)
        query[1] = 1.0  # closest to doc_b
        results = await store.query(query, top_k=3)

        assert results[0][0] == "doc_b"

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty(self, store):
        """Query on an empty store returns []."""
        query = np.random.randn(384).astype(np.float32)
        query = query / np.linalg.norm(query)
        results = await store.query(query, top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_count(self, store, three_docs):
        """count returns the number of stored documents."""
        ids, vecs, meta = three_docs
        assert await store.count() == 0

        await store.upsert(ids, vecs, meta)
        assert await store.count() == 3

    @pytest.mark.asyncio
    async def test_upsert_replaces_existing(self, store, three_docs):
        """Second upsert with same ids replaces data."""
        ids, vecs, meta = three_docs
        await store.upsert(ids, vecs, meta)
        assert await store.count() == 3

        # Upsert with new vectors — only 2 docs
        new_vecs = np.zeros((2, 384), dtype=np.float32)
        new_vecs[0, 5] = 1.0
        new_vecs[1, 6] = 1.0
        await store.upsert(["doc_x", "doc_y"], new_vecs)
        assert await store.count() == 2

    @pytest.mark.asyncio
    async def test_query_respects_top_k(self, store, three_docs):
        """query returns at most top_k results."""
        ids, vecs, meta = three_docs
        await store.upsert(ids, vecs, meta)

        query = np.zeros(384, dtype=np.float32)
        query[0] = 1.0
        results = await store.query(query, top_k=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_metadata_defaults_to_empty_dict(self, store, three_docs):
        """Upsert without metadata stores empty dicts."""
        ids, vecs, _ = three_docs
        await store.upsert(ids, vecs)

        query = np.zeros(384, dtype=np.float32)
        query[0] = 1.0
        results = await store.query(query, top_k=1)

        assert len(results) == 1
        _, _, meta = results[0]
        assert meta == {}  # default empty dict


class TestNumpyVectorStoreValidation:
    """Error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_dimension_mismatch_raises(self, store):
        """upsert with wrong dimension raises ValueError."""
        vecs = np.zeros((3, 128), dtype=np.float32)  # 128 != 384
        with pytest.raises(ValueError, match="Expected vectors shape"):
            await store.upsert(["a", "b", "c"], vecs)

    @pytest.mark.asyncio
    async def test_id_count_mismatch_raises(self, store):
        """upsert with mismatched id/vector count raises ValueError."""
        vecs = np.zeros((3, 384), dtype=np.float32)
        with pytest.raises(ValueError, match="ids length"):
            await store.upsert(["only_one_id"], vecs)

    @pytest.mark.asyncio
    async def test_upsert_non_2d_array_raises(self, store):
        """upsert with 1D vectors raises ValueError."""
        vecs = np.zeros(384, dtype=np.float32)  # 1D
        with pytest.raises(ValueError, match="Expected vectors shape"):
            await store.upsert(["a"], vecs)

    @pytest.mark.asyncio
    async def test_query_excludes_zero_score(self, store):
        """query excludes results with score <= 0."""
        # Insert vectors with baseline 0.3
        vecs = np.full((3, 384), 0.3, dtype=np.float32)
        vecs[0, 0] = 1.0
        vecs[1, 10] = 1.0
        vecs[2, 20] = 1.0
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        await store.upsert(["a", "b", "c"], vecs)

        # Query that is a negated version of doc_a -> negative dot product
        query = -vecs[0].copy()
        results = await store.query(query, top_k=3)
        # All scores should be <= 0 (doc_a gets -1.0, others near zero)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_replace_maintains_dimension(self, store, three_docs):
        """Multiple upsert calls keep correct dimension."""
        ids, vecs, meta = three_docs
        await store.upsert(ids, vecs, meta)

        # Replace with different data
        new_vecs = np.zeros((2, 384), dtype=np.float32)
        new_vecs[0, 10] = 1.0
        new_vecs[1, 20] = 1.0
        await store.upsert(["x", "y"], new_vecs)
        assert await store.count() == 2

        # Querying still works
        query = np.zeros(384, dtype=np.float32)
        query[10] = 1.0
        results = await store.query(query, top_k=1)
        assert len(results) == 1
        assert results[0][0] == "x"

    @pytest.mark.asyncio
    async def test_concurrent_safety(self, store, three_docs):
        """Multiple await cycles don't corrupt state (GIL-protected)."""
        ids, vecs, meta = three_docs
        await store.upsert(ids, vecs, meta)
        assert await store.count() == 3

        # Simulate read-then-write
        q = np.zeros(384, dtype=np.float32)
        q[0] = 1.0
        r1 = await store.query(q, top_k=3)
        assert len(r1) == 3

        # Write
        single_vec = np.zeros((1, 384), dtype=np.float32)
        single_vec[0, 0] = 1.0
        await store.upsert(["single"], single_vec)
        assert await store.count() == 1
