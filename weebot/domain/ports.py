"""Domain ports (interfaces) for weebot — zero external dependencies."""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

from weebot.domain.models import Project, Task


@runtime_checkable
class IModelProvider(Protocol):
    """Port for AI model providers (Kimi, DeepSeek, Claude, GPT)."""

    async def generate(
        self,
        prompt: str,
        task_type: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str: ...

    async def estimate_cost(self, prompt: str, task_type: str) -> float: ...


@runtime_checkable
class IRepository(Protocol):
    """Port for persistent project storage."""

    async def save_project(self, project: Project) -> None: ...
    async def load_project(self, project_id: str) -> Project: ...
    async def list_projects(self) -> list[dict[str, Any]]: ...
    async def delete_project(self, project_id: str) -> None: ...


@runtime_checkable
class INotifier(Protocol):
    """Port for multi-channel notifications."""

    async def notify(
        self,
        title: str,
        message: str,
        level: str = "info",
        project_id: str | None = None,
    ) -> None: ...


@runtime_checkable
class ITool(Protocol):
    """Port for execution tools (PowerShell, Browser, etc.)."""

    @property
    def name(self) -> str: ...

    async def execute(self, command: str) -> dict[str, Any]: ...
