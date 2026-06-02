"""SkillRetrieverPort — retrieves relevant skills for a task description (Tier 1.2).

Maps to LIFE-HARNESS "Procedural Skill Layer" (Section 4.3.2).  The port
abstracts how skills are indexed and matched — BM25 is the default, but
embedding-based retrieval can be swapped in without changing the caller.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.skill import SkillMatch


class SkillRetrieverPort(ABC):
    """Retrieves skills relevant to a task description.

    Called by ExecutorAgent at the start of each step to inject
    relevant procedural guidance into the system prompt.
    """

    @abstractmethod
    async def retrieve(
        self, task: str, top_k: int = 3
    ) -> list[SkillMatch]:
        """Return top-k skills most relevant to *task*.

        Args:
            task: The task description or step prompt.
            top_k: Maximum number of skills to return.

        Returns:
            List of SkillMatch ordered by relevance (highest first).
        """
        ...

    @abstractmethod
    async def refresh(self) -> None:
        """Rebuild the skill index (called when skills change).

        Must be safe to call while retrievals are in-flight.
        """
        ...
