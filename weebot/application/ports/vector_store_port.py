"""VectorStorePort — abstracts vector storage and similarity search.

Introduced to decouple ``SemanticSkillRetriever`` from numpy, enabling
future backends (Zvec, FAISS, pgvector) without retriever rewrites.
The default implementation is ``NumpyVectorStore`` in the infrastructure
layer — zero new dependencies.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class VectorStorePort(ABC):
    """Stores document vectors with metadata and supports top-k similarity search.

    All vectors are FP32 with a fixed dimension determined at store creation.
    Cosine similarity is the canonical distance metric.

    Implementations must be safe to call from concurrent coroutines (the
    retriever may call ``query`` while a background task calls ``upsert``).
    """

    @abstractmethod
    async def upsert(
        self,
        ids: list[str],
        vectors: np.ndarray,
        metadata: Optional[list[dict]] = None,
    ) -> None:
        """Insert or update documents.

        When an *id* already exists, its vector and metadata are replaced
        (upsert semantics).  The caller is responsible for L2-normalizing
        *vectors* before calling.

        Args:
            ids: Document identifiers.  Must match ``vectors.shape[0]``.
            vectors: FP32 array of shape ``(N, dim)``, L2-normalized.
            metadata: Optional per-document metadata dicts (N entries).
        """
        ...

    @abstractmethod
    async def query(
        self,
        vector: np.ndarray,
        top_k: int = 10,
    ) -> list[tuple[str, float, dict]]:
        """Return the *top_k* most similar documents by cosine similarity.

        Args:
            vector: FP32 query vector of shape ``(dim,)``, already L2-normalized.
            top_k: Maximum number of results.

        Returns:
            List of ``(id, score, metadata)`` tuples sorted by descending score.
            Score is cosine similarity in [0, 1].  Metadata is an empty dict
            when no metadata was stored by ``upsert``.
        """
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return the number of documents currently stored."""
        ...
