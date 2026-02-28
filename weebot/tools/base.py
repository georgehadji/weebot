"""BaseTool protocol — OpenManus-style function-calling tools for weebot."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from pydantic import BaseModel, ConfigDict


@dataclass
class ToolResult:
    """Result from any tool execution."""
    output: str
    error: str | None = None
    base64_image: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def __str__(self) -> str:
        if self.is_error:
            return f"ERROR: {self.error}"
        return self.output


class BaseTool(ABC, BaseModel):
    """Base class for all weebot function-calling tools."""
    name: str
    description: str
    parameters: dict  # JSON Schema object

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...

    def to_param(self) -> dict:
        """Convert to OpenAI function spec for tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ToolCollection:
    """Registry of tools; dispatches execute() by name."""

    def __init__(self, *tools: BaseTool) -> None:
        self._tools: dict[str, BaseTool] = {t.name: t for t in tools}

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def to_params(self) -> list[dict]:
        return [t.to_param() for t in self._tools.values()]

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        if name not in self._tools:
            return ToolResult(output="", error=f"Unknown tool: {name!r}")
        try:
            return await self._tools[name].execute(**kwargs)
        except Exception as exc:
            return ToolResult(output="", error=str(exc))
