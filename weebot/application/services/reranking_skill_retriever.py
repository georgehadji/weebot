"""RerankingSkillRetriever — wraps any SkillRetrieverPort with cross-encoder reranking.

Decorator pattern: takes an existing retriever (e.g. BM25), retrieves a
larger candidate set, then reranks candidates against the task description
using a cross-encoder model (Cohere Rerank via OpenRouter).

The ``SkillRetrieverPort`` contract already says "ordered by relevance" —
this wrapper improves the ordering without changing the interface.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.rerank_port import RerankPort
from weebot.application.ports.skill_retriever_port import SkillRetrieverPort
from weebot.config.model_refs import RERANK_MODEL_PRO
from weebot.domain.models.skill import SkillMatch

logger = logging.getLogger(__name__)

# Number of BM25 candidates to fetch before reranking.
# 20 gives the reranker enough candidates to find the best 3-5.
_CANDIDATE_POOL = 20


class RerankingSkillRetriever(SkillRetrieverPort):
    """Decorator that reranks skill candidates from a base retriever.

    Args:
        base_retriever: The underlying retriever (e.g. ``BM25SkillRetriever``).
        rerank: A ``RerankPort`` implementation for cross-encoder scoring.
        model: Rerank model ID (defaults to ``RERANK_MODEL_PRO``).
    """

    def __init__(
        self,
        base_retriever: SkillRetrieverPort,
        rerank: RerankPort,
        model: str = RERANK_MODEL_PRO,
    ) -> None:
        self._base = base_retriever
        self._rerank = rerank
        self._model = model

    # ── SkillRetrieverPort implementation ───────────────────────────

    async def retrieve(self, task: str, top_k: int = 3) -> list[SkillMatch]:
        """Retrieve top-K skills, reranked by semantic relevance to *task*."""
        # Phase 1: get a larger candidate pool from the base retriever
        candidates = await self._base.retrieve(task, top_k=_CANDIDATE_POOL)
        if len(candidates) <= top_k:
            return candidates  # not enough to rerank

        # Phase 2: rerank against the task description
        documents = [
            f"{c.skill_name}: {c.description or ''} {c.content_preview or ''}"
            for c in candidates
        ]
        try:
            reranked = await self._rerank.rerank(
                query=task,
                documents=documents,
                model=self._model,
                top_n=top_k,
            )
        except Exception as exc:
            logger.warning(
                "Skill rerank failed, falling back to base ordering: %s", exc
            )
            return candidates[:top_k]

        # Phase 3: map rerank results back to SkillMatch objects
        result: list[SkillMatch] = []
        for rr in reranked:
            if rr.index < len(candidates):
                original = candidates[rr.index]
                result.append(
                    SkillMatch(
                        skill_name=original.skill_name,
                        description=original.description,
                        content_preview=original.content_preview,
                        score=rr.score,
                    )
                )

        return result

    async def refresh(self) -> None:
        """Delegate index rebuild to the base retriever."""
        await self._base.refresh()
