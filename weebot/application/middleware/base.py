"""Middleware ABC — interceptor pattern for agent request/response processing.

Each middleware wraps the LLM request/response cycle, allowing tools to be
filtered, state to be injected, and responses to be transformed before the
agent sees them.

Inspired by Deep Agents' middleware stack — but simplified for weebot's
immutable-state architecture.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MiddlewareRequest:
    """The intercepted request to the LLM."""
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    step_id: str = ""
    step_description: str = ""


@dataclass
class MiddlewareResponse:
    """The intercepted response from the LLM."""
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResult:
    """Result of a single tool call within the middleware pipeline."""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    error: Optional[str] = None
    is_error: bool = False
    duration_ms: float = 0.0

    @classmethod
    def from_raw(cls, raw: Any) -> "ToolCallResult":
        """Convert from a ToolResult or similar."""
        if hasattr(raw, "output"):
            return cls(
                tool_name=getattr(raw, "tool_name", ""),
                output=getattr(raw, "output", ""),
                error=getattr(raw, "error", None),
                is_error=getattr(raw, "is_error", False),
            )
        return cls()


class Middleware(ABC):
    """Base class for agent middleware.

    Middleware can intercept three lifecycle events:
    1. before_request — before the LLM is called (can modify messages/tools)
    2. after_response — after the LLM responds (can modify response)
    3. after_tool_call — after each tool call in the step (can modify result)
    """

    @abstractmethod
    def name(self) -> str:
        """Human-readable middleware name for logging."""
        ...

    async def before_request(
        self,
        request: MiddlewareRequest,
        state: dict[str, Any],
    ) -> tuple[MiddlewareRequest, dict[str, Any]]:
        """Called before the LLM request is sent.

        Override to inject system prompt context, filter tools, or modify messages.
        Return the (possibly modified) request and state.
        """
        return request, state

    async def after_response(
        self,
        response: MiddlewareResponse,
        request: MiddlewareRequest,
        state: dict[str, Any],
    ) -> tuple[MiddlewareResponse, dict[str, Any]]:
        """Called after the LLM responds but before tool calls are dispatched.

        Override to inspect the response, inject recovery messages, or abort.
        Return the (possibly modified) response and state.
        """
        return response, state

    async def after_tool_call(
        self,
        result: ToolCallResult,
        state: dict[str, Any],
    ) -> tuple[ToolCallResult, dict[str, Any]]:
        """Called after each individual tool call completes.

        Override to inspect tool results, inject trajectory monitor state,
        or modify the result before it reaches the agent.
        """
        return result, state
