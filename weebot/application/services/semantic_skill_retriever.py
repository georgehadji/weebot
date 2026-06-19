"""SemanticSkillRetriever — embedding-based skill retrieval (Tier 1.2, Phase 3).

Replaces BM25 word-overlap with cosine similarity over 384-dim embeddings
produced by sentence-transformers (all-MiniLM-L6-v2).  Index is rebuilt via
``refresh()`` whenever the skill registry changes.

Gated behind ``SEMANTIC_SKILL_RETRIEVAL_ENABLED`` — when the flag is off,
``_create_skill_retriever()`` in the DI container falls back to the BM25 path.

Maps to SkillWeaver's bi-encoder + cosine similarity stage, substituting
numpy brute-force search for FAISS (unnecessary below 1,000 skills).

The underlying vector store is abstracted behind ``VectorStorePort``.
Default is ``NumpyVectorStore`` (in-memory, numpy).  A future persistent
backend (e.g. Zvec) can be swapped without changing this class.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from weebot.application.ports.skill_retriever_port import SkillRetrieverPort
from weebot.application.ports.vector_store_port import VectorStorePort
from weebot.application.skills.skill_registry import SkillRegistry
from weebot.domain.models.skill import SkillMatch
from weebot.infrastructure.adapters.numpy_vector_store import NumpyVectorStore

logger = logging.getLogger(__name__)

# Default embedding dimension for all-MiniLM-L6-v2
_DEFAULT_DIM = 384


class SemanticSkillRetriever(SkillRetrieverPort):
    """Embedding-based skill retrieval over the skill registry.

    Uses ``LocalEmbeddings`` (sentence-transformers all-MiniLM-L6-v2, 384-dim)
    via the singleton in ``weebot.qmd_integration.embeddings``.  At < 500 skills
    brute-force numpy cosine similarity is faster than FAISS (no C++ build, no
    index construction overhead).

    Args:
        registry: Loaded ``SkillRegistry`` instance.
        top_k: Default number of results to return when ``top_k`` is not
            provided to ``retrieve()``.
        store: Backing vector store.  Defaults to ``NumpyVectorStore(dim=384)``.
            Swap to a persistent store (e.g. ZvecVectorStore) when needed.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        top_k: int = 3,
        store: Optional[VectorStorePort] = None,
    ) -> None:
        self._registry = registry
        self._top_k = top_k
        self._store = store or NumpyVectorStore(dim=_DEFAULT_DIM)
        self._index_built = False
        self._embeddings = None  # LocalEmbeddings singleton, lazy
        logger.debug(
            "SemanticSkillRetriever created (store=%s)",
            type(self._store).__name__,
        )

    # ── Port implementation ─────────────────────────────────────────

    async def retrieve(self, task: str, top_k: int = 3) -> list[SkillMatch]:
        """Return top-k skills by cosine similarity of *task* embeddings.

        Builds the index lazily on first call if ``refresh()`` hasn't been
        called explicitly.
        """
        if not self._index_built:
            await self.refresh()
            if not self._index_built:
                return []  # refresh failed or empty registry

        k = top_k if top_k > 0 else self._top_k

        try:
            emb = self._get_embeddings()
            query_result = await emb.embed_query(task)
            query_vec = np.array(query_result.embedding, dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm > 0:
                query_vec = query_vec / query_norm
            else:
                return []
        except Exception as exc:
            logger.warning("SemanticSkillRetriever: query embedding failed — %s", exc)
            return []

        store_results = await self._store.query(query_vec, top_k=k)

        return [
            SkillMatch(
                skill_name=doc_id,
                description=meta.get("description", ""),
                content_preview=meta.get("preview", ""),
                score=round(score, 4),
            )
            for doc_id, score, meta in store_results
        ]

    async def refresh(self) -> None:
        """Rebuild the embedding index from the current skill registry.

        Encodes all skills via ``LocalEmbeddings`` and pushes them into
        the backing vector store via ``upsert``.
        """
        skills = self._registry.list_all()
        if not skills:
            self._index_built = False
            logger.info("SemanticSkillRetriever: empty index (no skills loaded)")
            return

        names: list[str] = []
        descriptions: list[str] = []
        previews: list[str] = []
        texts: list[str] = []

        for skill_name, skill in skills.items():
            desc = getattr(skill, "description", "") or ""
            content = getattr(skill, "content", "") or ""
            text = f"{skill_name}: {desc} {content[:500]}"
            text = text.strip()
            if text:
                names.append(skill_name)
                descriptions.append(desc[:200])
                previews.append(text[:300])
                texts.append(text)

        if not texts:
            self._index_built = False
            logger.info("SemanticSkillRetriever: empty index (no texts)")
            return

        # Encode all documents via LocalEmbeddings
        try:
            emb = self._get_embeddings()
            results = await emb.embed_documents(texts)
            matrix = np.array([r.embedding for r in results], dtype=np.float32)
            # L2-normalize so cosine similarity = dot product
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0  # guard against zero vectors
            matrix = matrix / norms
        except Exception as exc:
            logger.error("SemanticSkillRetriever: embedding failed — %s", exc)
            self._index_built = False
            return

        # Push to vector store
        metadata = [
            {"description": d, "preview": p}
            for d, p in zip(descriptions, previews)
        ]
        await self._store.upsert(names, matrix, metadata)
        self._index_built = True
        logger.info(
            "SemanticSkillRetriever: index built — %d skills (%s)",
            len(names),
            type(self._store).__name__,
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _get_embeddings(self):
        """Lazy-load the LocalEmbeddings singleton."""
        if self._embeddings is None:
            from weebot.qmd_integration.embeddings import get_local_embeddings

            self._embeddings = get_local_embeddings()
        return self._embeddings
