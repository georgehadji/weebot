"""Port for episodic summary storage and semantic retrieval."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple


class SummaryRepositoryPort(ABC):
    """Abstract interface for storing and retrieving session summaries with embeddings."""

    @abstractmethod
    async def save_summary(
        self,
        session_id: str,
        summary: str,
        embedding: List[float],
    ) -> None:
        """Persist a session summary and its embedding vector."""
        ...

    @abstractmethod
    async def find_similar(
        self,
        embedding: List[float],
        k: int = 3,
    ) -> List[Tuple[str, str, float]]:
        """Return top-k similar summaries as (session_id, summary, similarity_score)."""
        ...
