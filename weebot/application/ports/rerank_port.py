"""RerankPort — abstract interface for cross-encoder reranking.

Abstracts how search results, skill candidates, or document lists are
reordered by semantic relevance to a query.  The default implementation
calls the OpenRouter rerank endpoint (Cohere models), but any reranker
can be swapped in behind this port.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.rerank import RerankResult


class RerankPort(ABC):
    """Reorder *documents* by relevance to *query*.

    Implementations call a cross-encoder reranker (e.g. Cohere via
    OpenRouter) and return results sorted by relevance score descending.
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """Rerank *documents* against *query*.

        Args:
            query: The search query or task description.
            documents: List of document texts to score.
            model: Override the default rerank model.
            top_n: If set, return only the top-N results.

        Returns:
            List of ``RerankResult`` sorted by ``score`` descending.
        """
        ...
