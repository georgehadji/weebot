"""Port for episodic summaries: what a successful past session did, found by task."""

from __future__ import annotations

from abc import ABC, abstractmethod


class SummaryRepositoryPort(ABC):
    """Store a session's summary under its task, and find summaries for a similar task.

    The adapter owns similarity (embeddings when available, token overlap
    otherwise), so callers pass text, not vectors.
    """

    @abstractmethod
    async def save_summary(self, session_id: str, task: str, summary: str) -> None:
        """Persist *summary* of the session that worked on *task*."""
        ...

    @abstractmethod
    async def find_similar(self, task: str, k: int = 3) -> list[tuple[str, str, str, float]]:
        """Top *k* matches as ``(session_id, task, summary, similarity)``, best first."""
        ...

    @abstractmethod
    async def delete_by_session_id(self, session_id: str) -> int:
        """Remove the session's summary; return how many rows went (the delete cascade)."""
        ...
