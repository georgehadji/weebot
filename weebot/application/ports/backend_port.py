"""BackendPort — unified I/O interface for all filesystem and execution operations.

Replaces the pattern where every tool builds its own execution path with a single
ABC backed by SandboxPort. Tools call backend.read/write/edit/execute instead of
constructing subprocess calls directly.

Implementations must be fail-open: return error results on any exception.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.backend_results import (
    EditResult,
    ExecuteResult,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)


class BackendPort(ABC):
    """Unified I/O interface for all filesystem and execution operations."""

    @abstractmethod
    async def ls(self, path: str) -> LsResult:
        """List entries in a directory."""
        ...

    @abstractmethod
    async def read(self, file_path: str, offset: int = 0, limit: int = 100) -> ReadResult:
        """Read file content with optional pagination."""
        ...

    @abstractmethod
    async def write(self, file_path: str, content: str) -> WriteResult:
        """Write content to a new file."""
        ...

    @abstractmethod
    async def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Perform exact string replacement in an existing file."""
        ...

    @abstractmethod
    async def glob(self, pattern: str, path: Optional[str] = None) -> GlobResult:
        """Find files matching a glob pattern."""
        ...

    @abstractmethod
    async def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        glob_filter: Optional[str] = None,
    ) -> GrepResult:
        """Search for literal text pattern in files."""
        ...

    @abstractmethod
    async def execute(
        self,
        command: str,
        timeout: Optional[int] = None,
    ) -> ExecuteResult:
        """Execute a shell command."""
        ...
