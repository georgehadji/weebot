"""NumpyVectorStore — in-memory VectorStorePort backed by numpy.

Default implementation requiring no additional dependencies.  Uses
brute-force dot product after L2 normalization — optimal below ~500 vectors
where index construction overhead outweighs search time.

Not persistent — data is lost on process exit.  For persistent storage
use a future ``ZvecVectorStore`` or similar backend.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from weebot.application.ports.vector_store_port import VectorStorePort


class NumpyVectorStore(VectorStorePort):
    """In-memory vector store using brute-force numpy cosine similarity.

    Args:
        dim: Fixed embedding dimension (e.g. 384 for all-MiniLM-L6-v2).
            Vectors passed to ``upsert`` must match this dimension.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim
        self._ids: list[str] = []
        self._vectors: Optional[np.ndarray] = None  # shape (N, dim)
        self._metadata: list[dict] = []

    # ── VectorStorePort implementation ─────────────────────────────

    async def upsert(
        self,
        ids: list[str],
        vectors: np.ndarray,
        metadata: Optional[list[dict]] = None,
    ) -> None:
        """Replace all stored documents with the given batch.

        The caller (``SemanticSkillRetriever``) rebuilds the entire index on
        every ``refresh()``, so this implementation performs a wholesale
        replace rather than incremental upsert.  A future persistent backend
        (e.g. Zvec) can implement true incremental upsert without changing
        the port contract.
        """
        if vectors.ndim != 2 or vectors.shape[1] != self._dim:
            raise ValueError(
                f"Expected vectors shape (N, {self._dim}), got {vectors.shape}"
            )
        if len(ids) != vectors.shape[0]:
            raise ValueError(
                f"ids length ({len(ids)}) != vectors rows ({vectors.shape[0]})"
            )

        self._ids = list(ids)
        self._vectors = vectors.copy()
        self._metadata = list(metadata) if metadata else [{}] * len(ids)

    async def query(
        self,
        vector: np.ndarray,
        top_k: int = 10,
    ) -> list[tuple[str, float, dict]]:
        """Brute-force cosine similarity via dot product on L2-normalized vectors.

        Args:
            vector: FP32 query vector of shape ``(dim,)``, L2-normalized.
            top_k: Maximum number of results.

        Returns:
            List of ``(id, score, metadata)`` tuples sorted by descending score.
            Results with score <= 0.0 are excluded (no similarity).  Returns
            empty list when the store is empty.
        """
        if self._vectors is None or len(self._ids) == 0:
            return []

        k = min(top_k, len(self._ids))
        scores = np.dot(self._vectors, vector)
        top_indices = np.argsort(scores)[::-1][:k]

        results: list[tuple[str, float, dict]] = []
        for idx in top_indices:
            s = float(scores[idx])
            if s <= 0.0:
                continue
            results.append((self._ids[idx], s, self._metadata[idx]))
        return results

    async def count(self) -> int:
        """Return the number of documents currently stored."""
        return len(self._ids)
