"""BaseTool — domain-level interface contract for agent tools.

This is the pure ABC + interface contract used by ports and models.
Moved here from ``weebot/tools/base.py`` during ARCH-AUDIT-V2 B5
so that application ports can depend on the domain layer directly
rather than reaching into the tools package.

All concrete tools continue to import from ``weebot.tools.base``
(which re-exports this class).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict


class BaseTool(ABC, BaseModel):
    """Base class for all weebot function-calling tools.

    This ABC defines the contract every tool must fulfil: a name,
    a JSON-Schema description of its parameters, an async execute
    entry point, and optional lifecycle hooks.

    Concrete implementations live under ``weebot/tools/`` and import
    via ``weebot.tools.base`` (which re-exports from here).
    """

    name: str
    description: str
    parameters: dict  # JSON Schema object
    allowed_roles: list[str] = ["*"]  # Roles authorized to use this tool. ["*"] = all roles.

    # Phase 2: Concurrency cap (0 = unlimited). Set to 1 for tools that
    # share a resource (browser, screen, voice, computer_use).
    max_concurrent: int = 0

    # Phase 3: Per-tool timeout in seconds (default 60).
    default_timeout_seconds: int = 60

    # Phase 4: Truncation strategy for oversized output.
    # "head" = keep start (default), "tail" = keep end, "boundary" = last record boundary.
    truncation_strategy: str = "head"

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: F821 — forward ref
        ...

    async def health_check(self) -> bool:
        """Return False if this tool's runtime dependencies are unavailable.

        Default implementation returns True (healthy). Override in tools
        that depend on external services or system-level packages.
        """
        return True

    async def close(self) -> None:
        """Release external resources acquired by this tool.

        Override in tools that allocate OS resources (browser, subprocess,
        MCP client, voice/audio streams).  Called by the tool registry or
        task runner when a tool session ends.

        Default implementation is a no-op — tools that don't acquire
        external resources don't need to override this.
        """
        return

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


__all__ = ["BaseTool"]
