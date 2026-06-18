"""FileStoragePort — abstract port for file read/write operations.

Application-layer services MUST NOT use open() or os.path directly.
They should depend on this port for all filesystem access, making
I/O testable and swappable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class FileStoragePort(ABC):
    """Port for reading and writing files on the local filesystem.

    Covers the common patterns found in application services: reading
    YAML/JSON/text config files and writing output files.
    """

    @abstractmethod
    async def read_text(self, path: str) -> str:
        """Read a text file.  Raises FileNotFoundError if missing."""

    @abstractmethod
    async def write_text(self, path: str, content: str) -> None:
        """Write a text file, creating parent directories as needed."""

    @abstractmethod
    async def read_yaml(self, path: str) -> dict[str, Any]:
        """Read and parse a YAML file.  Returns empty dict on missing file."""

    @abstractmethod
    async def write_yaml(self, path: str, data: dict[str, Any]) -> None:
        """Write a dict as YAML."""

    @abstractmethod
    async def read_json(self, path: str) -> Any:
        """Read and parse a JSON file.  Raises FileNotFoundError if missing."""

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Return True if the path exists on disk."""

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete a file.  Returns True if it existed."""
