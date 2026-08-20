"""Domain models for composite MCP tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SubToolCall(BaseModel):
    """A single step inside a composite tool workflow."""

    tool_name: str = Field(description="Name of the atomic tool to invoke")
    arguments: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", description="Human-readable purpose")
    capture_output_as: str | None = Field(
        default=None, description="Variable name to store this step's output for later steps"
    )


class CompositeToolSpec(BaseModel):
    """Specification for a composite MCP tool that wraps a workflow."""

    name: str = Field(description="MCP tool name exposed to clients")
    description: str = Field(description="Description shown in list_tools")
    sub_tools: list[SubToolCall] = Field(description="Ordered steps to execute")
    hidden_atomic_tools: list[str] = Field(
        default_factory=list,
        description="Atomic tool names to hide from list_tools when this composite is enabled",
    )
    transaction_policy: Literal["all_or_none", "best_effort"] = Field(
        default="best_effort", description="Whether a failed step aborts the whole workflow"
    )


class CompositeResult(BaseModel):
    """Result returned by a composite tool execution."""

    success: bool
    summary: str
    sub_results: list[dict[str, Any]]
    aborted_after_failure: bool = Field(default=False)


@runtime_checkable
class CompositeToolResultLike(Protocol):
    """Minimal protocol for results returned by atomic sub-tools.

    This keeps the composite executor decoupled from ``weebot.tools.base.ToolResult``
    so infrastructure can remain independent of the tools layer.
    """

    is_error: bool
    output: str
    error: str | None


# Async callable invoked by the composite executor to run an atomic tool.
CompositeToolDispatcher = Callable[..., Awaitable[Any]]
