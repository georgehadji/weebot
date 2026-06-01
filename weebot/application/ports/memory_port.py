"""MemoryPort — abstract storage for persistent cross-session memory."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class MemoryPort(ABC):
    """Port for persistent memory storage.

    Implementations store §-delimited entries in named files.
    """

    @abstractmethod
    async def read_entries(self, file: str) -> List[str]:
        """Return all entries in *file*, or empty list if file doesn't exist."""
        ...

    @abstractmethod
    async def write_entries(self, file: str, entries: List[str]) -> None:
        """Overwrite *file* with *entries*, joining with the § delimiter."""
        ...

    @abstractmethod
    async def read_snapshot(self) -> str:
        """Return a formatted snapshot of all memory files for system prompt injection.

        Returns an empty string if no memory files contain data.
        """
        ...
