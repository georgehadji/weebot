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
        import time
        
        if name not in self._tools:
            return ToolResult.error_result(
                error=f"Unknown tool: {name!r}",
                execution_time_ms=0.0,
                retry_count=0
            )
        
        start_time = time.time()
        retry_count = 0
        max_retries = kwargs.pop("_max_retries", 0)
        
        while True:
            try:
                result = await self._tools[name].execute(**kwargs)
                
                # Add execution metadata
                execution_time_ms = (time.time() - start_time) * 1000
                result.metadata.update({
                    "execution_time_ms": execution_time_ms,
                    "retry_count": retry_count,
                    "tool_name": name,
                })
                
                return result
                
            except Exception as exc:
                retry_count += 1
                
                if retry_count > max_retries:
                    execution_time_ms = (time.time() - start_time) * 1000
                    return ToolResult.error_result(
                        error=str(exc),
                        execution_time_ms=execution_time_ms,
                        retry_count=retry_count - 1,
                        tool_name=name
                    )
                
                # Simple backoff before retry
                await __import__('asyncio').sleep(0.1 * retry_count)
