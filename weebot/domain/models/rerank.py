"""Rerank domain models — pure dataclasses for rerank requests and results.

No imports from outer layers (application, infrastructure, interfaces, core).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RerankResult:
    """A single reranked document with its relevance score.

    Attributes:
        index: Original position in the input ``documents`` list (0-based).
        document: The document text that was scored.
        score: Relevance score from the reranker (0.0–1.0, higher = more relevant).
    """

    index: int
    document: str
    score: float


@dataclass
class RerankRequest:
    """Input for a rerank call.

    Attributes:
        query: The search query or task description to score against.
        documents: List of document texts to rerank.
        model: OpenRouter-qualified rerank model ID.
        top_n: If set, return only the top-N results.
    """

    query: str
    documents: list[str]
    model: str
    top_n: int | None = None
