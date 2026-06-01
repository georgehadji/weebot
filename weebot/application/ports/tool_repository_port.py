"""Port interface for tool data persistence.
Replaces raw sqlite3.connect() calls in the tools layer.
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class ToolRepositoryPort(ABC):
    """Storage abstraction for knowledge notes, product requirements,
    and video sources used by tools."""

    @abstractmethod
    async def query_notes(self, search: str = "", limit: int = 20) -> list[dict]: ...

    @abstractmethod
    async def save_note(
        self, title: str, content: str, tags: list[str] | None = None
    ) -> str: ...

    @abstractmethod
    async def delete_note(self, note_id: str) -> bool: ...

    @abstractmethod
    async def get_video_sources(self, limit: int = 50) -> list[dict]: ...

    @abstractmethod
    async def save_video_source(self, url: str, title: str = "", metadata: dict | None = None) -> str: ...

    @abstractmethod
    async def get_requirements(
        self, status: str | None = None
    ) -> list[dict]: ...

    @abstractmethod
    async def save_requirement(
        self, title: str, description: str, priority: str = "medium"
    ) -> str: ...
