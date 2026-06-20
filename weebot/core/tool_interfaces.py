"""Tool interfaces — minimal abstractions for core layer.

Clean Architecture requires core to depend on abstractions, not concrete
tool implementations.  `AgentTool` and `ToolCollection` define what core
needs; infrastructure (`weebot/tools/`) provides implementations.

All concrete tool imports are deferred to inside functions so they only
load when the specific tool path is activated, not at module import time.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentTool(Protocol):
    """Minimal tool interface — what core agent code needs.

    Satisfied by ``weebot.tools.base.BaseTool`` (which has ``name``,
    ``description``, and ``async execute(**kwargs) -> ToolResult``).
    """
    name: str
    description: str

    async def execute(self, **kwargs: Any) -> Any:
        ...


class ToolFactory(Protocol):
    """Creates ``AgentTool`` instances from specifications."""
    def create(self, spec: dict) -> AgentTool:
        ...
