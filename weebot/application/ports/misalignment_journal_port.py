"""Port: persistent misalignment journal for cross-session avoidance."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.misalignment_entry import MisalignmentEntry


class MisalignmentJournalPort(ABC):
    """Write and read misalignment entries scoped to a project path."""

    @abstractmethod
    async def record(self, entry: MisalignmentEntry) -> None:
        """Persist a new misalignment entry."""

    @abstractmethod
    async def get_recent(self, project_path: str, limit: int = 5) -> list[MisalignmentEntry]:
        """Return the most recent entries for a project, newest first."""
