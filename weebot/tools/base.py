"""BaseTool protocol — OpenManus-style function-calling tools for weebot."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


@dataclass
class ToolResult:
    """
    Result from any tool execution.
    
    Enhanced with structured JSON output and metadata tracking for Phase 2.
    Maintains backward compatibility with existing output/error fields.
    
    Attributes:
        output: Legacy text output (maintained for compatibility)
        error: Legacy error message (maintained for compatibility)
        base64_image: Optional base64-encoded image
        success: Whether the tool execution succeeded
        data: Structured JSON-serializable data
        metadata: Execution metadata (timing, retries, circuit breaker state)
    """
    # Legacy fields (maintained for backward compatibility)
    output: str = ""
    error: Optional[str] = None
    base64_image: Optional[str] = None
    
    # New structured fields (Phase 2)
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure consistency between legacy and new fields."""
        # Derive success from error if not explicitly set
        if self.error is not None and self.success:
            self.success = False
        
        # Derive error from success if not explicitly set
        if not self.success and self.error is None:
            self.error = "Tool execution failed"

    @property
    def is_error(self) -> bool:
        """Check if result represents an error (legacy compatibility)."""
        return not self.success or self.error is not None

    def __str__(self) -> str:
        if self.is_error:
            return f"ERROR: {self.error}"
        return self.output
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert result to dictionary for serialization.
        
        Returns:
            Dict with all result fields
        """
        return {
            "output": self.output,
            "error": self.error,
            "success": self.success,
            "data": self.data,
            "metadata": self.metadata,
            "has_image": self.base64_image is not None,
        }
    
    @classmethod
    def success_result(
        cls,
        output: str = "",
        data: Optional[Dict[str, Any]] = None,
        **metadata
    ) -> "ToolResult":
        """
        Create a successful result.
        
        Args:
            output: Text output
            data: Structured data
            **metadata: Execution metadata (execution_time_ms, retry_count, etc.)
            
        Returns:
            ToolResult with success=True
        """
        return cls(
            output=output,
            success=True,
            data=data or {},
            metadata=metadata
        )
    
    @classmethod
    def error_result(
        cls,
        error: str,
        output: str = "",
        **metadata
    ) -> "ToolResult":
        """
        Create an error result.
        
        Args:
            error: Error message
            output: Any partial output before error
            **metadata: Execution metadata
            
        Returns:
            ToolResult with success=False
        """
        return cls(
            output=output,
            error=error,
            success=False,
            metadata=metadata
        )


class BaseTool(ABC, BaseModel):
    """Base class for all weebot function-calling tools."""
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
    async def execute(self, **kwargs: Any) -> ToolResult: ...

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


# ToolCollection has been promoted to weebot.application.models.tool_collection.
# This module-level __getattr__ provides a lazy backward-compatible re-export
# that avoids a circular import between tools/base and application/models.


def __getattr__(name: str):
    if name == "ToolCollection":
        from weebot.application.models.tool_collection import (
            ToolCollection as _ToolCollection,
        )
        return _ToolCollection
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
