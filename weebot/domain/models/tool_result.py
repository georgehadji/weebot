"""ToolResult — pure domain value object for tool execution outcomes.

Moved from weebot/tools/base.py to the domain layer so application
services, agents, and ports can import it without depending on the
tools (infrastructure) layer.  The tools layer re-exports this for
backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    error: str | None = None
    base64_image: str | None = None

    # New structured fields (Phase 2)
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

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

    def to_dict(self) -> dict[str, Any]:
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
        cls, output: str = "", data: dict[str, Any] | None = None, **metadata
    ) -> ToolResult:
        """
        Create a successful result.

        Args:
            output: Text output
            data: Structured data
            **metadata: Execution metadata (execution_time_ms, retry_count, etc.)

        Returns:
            ToolResult with success=True
        """
        return cls(output=output, success=True, data=data or {}, metadata=metadata)

    @classmethod
    def error_result(cls, error: str, output: str = "", **metadata) -> ToolResult:
        """
        Create an error result.

        Args:
            error: Error message
            output: Any partial output before error
            **metadata: Execution metadata

        Returns:
            ToolResult with success=False
        """
        return cls(output=output, error=error, success=False, metadata=metadata)
