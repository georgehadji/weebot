"""QmdRagAdapter builds the real engine and calls its real method.

Found by the dead-code audit: the adapter imported ``QMDRagEngine`` (the class is
``RAGEngine``) and called ``.search`` (the engine has ``.retrieve``). The broad
``except`` turned both into an empty result, so the adapter could never return anything.
"""

from __future__ import annotations

from weebot.infrastructure.adapters.qmd_rag_adapter import QmdRagAdapter
from weebot.qmd_integration import rag_engine
from weebot.qmd_integration.rag_engine import RAGContext, RetrievedChunk


def _context(query, n):
    chunks = [
        RetrievedChunk(
            content=f"chunk {i}", source_file="a.md", docid=str(i), score=1.0, chunk_index=i
        )
        for i in range(n)
    ]
    return RAGContext(query=query, chunks=chunks, total_tokens=10, sources=["a.md"])


async def test_the_lazily_built_engine_answers(monkeypatch):
    async def retrieve(self, query, **_kw):
        return _context(query, 5)

    monkeypatch.setattr(rag_engine.RAGEngine, "retrieve", retrieve)
    assert await QmdRagAdapter().search("auth setup", top_k=2) == ["chunk 0", "chunk 1"]
