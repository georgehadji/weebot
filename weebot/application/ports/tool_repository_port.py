"""Port interface for tool data persistence.
Replaces raw sqlite3.connect() calls in the tools layer.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional


class ToolRepositoryPort(ABC):
    """Storage abstraction for knowledge notes, product requirements,
    and video sources used by tools."""

    # ── Notes ────────────────────────────────────────────────────────

    @abstractmethod
    async def query_notes(self, search: str = "", limit: int = 20) -> list[dict]: ...

    @abstractmethod
    async def get_note(self, note_id: str) -> Optional[dict]:
        """Return a single note by ID, or None if not found."""
        ...

    @abstractmethod
    async def save_note(
        self, title: str, content: str, tags: Optional[list[str]] = None,
        project_id: str = "",
    ) -> str: ...

    @abstractmethod
    async def list_notes(
        self, project_id: str = "", tags: Optional[list[str]] = None, limit: int = 50
    ) -> list[dict]: ...

    @abstractmethod
    async def delete_note(self, note_id: str) -> bool: ...

    # ── Video sources ────────────────────────────────────────────────

    @abstractmethod
    async def get_video_sources(
        self, project_id: str = "", limit: int = 50
    ) -> list[dict]: ...

    @abstractmethod
    async def save_video_source(
        self, url: str, title: str = "",
        project_id: str = "", metadata: Optional[dict] = None,
    ) -> str: ...

    # ── Requirements ─────────────────────────────────────────────────

    @abstractmethod
    async def get_requirements(
        self, project_id: str = "", status: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> list[dict]: ...

    @abstractmethod
    async def save_requirement(
        self, title: str, description: str, priority: str = "medium",
        project_id: str = "",
    ) -> str: ...

    @abstractmethod
    async def update_requirement_status(self, req_id: str, new_status: str) -> bool:
        """Update the status of a requirement. Returns False if not found."""
        ...
