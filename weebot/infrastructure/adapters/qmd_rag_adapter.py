"""QmdRagAdapter — RagPort implementation wrapping the QMD RAG engine.

Wraps ``weebot.qmd_integration.rag_engine.QMDRagEngine`` in a hexagonal
port/adapter pattern so the application layer can use RAG retrieval
without importing infrastructure directly.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.rag_port import RagPort

logger = logging.getLogger(__name__)


class QmdRagAdapter(RagPort):
    """Adapter wrapping the QMD RAG engine behind the RagPort interface.

    The QMD RAG engine provides hybrid BM25 + vector search with
    smart chunking and citation support.

    Args:
        rag_engine: Optional pre-configured QMDRagEngine instance.
            If None, one is created lazily on first search.
    """

    def __init__(self, rag_engine=None) -> None:
        self._engine = rag_engine

    async def search(self, query: str, top_k: int = 3) -> list[str]:
        if not query.strip():
            return []

        try:
            if self._engine is None:
                from weebot.qmd_integration.rag_engine import QMDRagEngine
                self._engine = QMDRagEngine()
            results = await self._engine.search(query, top_k=top_k)
            return [r.content for r in results]
        except Exception as exc:
            logger.warning("QmdRagAdapter search failed: %s", exc)
            return []


class NoOpRagAdapter(RagPort):
    """No-op RAG adapter that always returns empty results.

    Used as default when no RAG backend is configured.
    """

    async def search(self, query: str, top_k: int = 3) -> list[str]:
        return []
