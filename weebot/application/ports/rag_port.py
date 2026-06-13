"""Port for RAG-based memory retrieval.

Defines the abstract interface for searching across embedded skill
content and past session data. Implementations perform hybrid BM25 + vector
search and return ranked text results.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RagPort(ABC):
    """Abstract port for RAG-based memory retrieval.

    Implementations:
    - QmdRagAdapter — wraps the QMD RAG engine (local GGUF embeddings)
    - Fallback: NoOpRagAdapter — returns empty results (graceful degradation)
    """

    @abstractmethod
    async def search(self, query: str, top_k: int = 3) -> list[str]:
        """Search memory for content relevant to *query*.

        Args:
            query: Search query string.
            top_k: Maximum number of results to return.

        Returns:
            List of relevant text snippets, empty list if nothing found.
        """
        ...
