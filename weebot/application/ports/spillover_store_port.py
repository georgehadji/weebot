"""Port for storing the full text of a tool output that was too long for the context (H7)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SpillRef:
    path: str  # where the model can read the full text back, with file_editor view
    chars: int


class SpilloverStorePort(ABC):
    @abstractmethod
    async def write(self, session_id: str, call_id: str, text: str) -> SpillRef:
        """Store *text* for one tool call of a session."""

    @abstractmethod
    async def purge(self, session_id: str) -> int:
        """Delete everything stored for a session (session-delete cascade). Returns the count."""
