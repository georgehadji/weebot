"""Domain models for BackendPort I/O operations.

Pure domain: no imports from Application or Infrastructure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LsResult:
    """Result of a directory listing operation."""
    entries: list[dict] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class ReadResult:
    """Result of a file read operation."""
    content: str = ""
    line_count: int = 0
    total_lines: int = 0
    truncated: bool = False
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class WriteResult:
    """Result of a file write operation."""
    path: str = ""
    size_bytes: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class EditResult:
    """Result of a file edit operation."""
    path: str = ""
    occurrences: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class GlobResult:
    """Result of a glob pattern search."""
    matches: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class GrepMatch:
    """A single match from a grep search."""
    path: str = ""
    line: int = 0
    text: str = ""


@dataclass
class GrepResult:
    """Result of a grep text search."""
    matches: list[GrepMatch] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class ExecuteResult:
    """Result of a shell command execution."""
    output: str = ""
    exit_code: int = 0
    truncated: bool = False
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.error is None
