"""MiddlewareChain — ordered pipeline of Middleware instances.

Each middleware can intercept three lifecycle events:
1. before_request — before the LLM is called (can modify messages/tools)
2. after_response — after the LLM responds (can modify response)
3. after_tool_call — after each tool call in the step (can modify result)

Middleware execute in declaration order, threading a state dict through.
The chain is stateless — each call creates a fresh state dict, so
middleware instances can be reused across steps safely.
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.middleware.base import (
    Middleware,
    MiddlewareRequest,
    MiddlewareResponse,
    ToolCallResult,
)

logger = logging.getLogger(__name__)


class MiddlewareChain:
    """Ordered pipeline of Middleware instances.

    Args:
        middlewares: Initial list of middleware instances (optional).
    """

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self._middlewares: list[Middleware] = list(middlewares or [])

    def is_empty(self) -> bool:
        """Return True if no middleware are registered."""
        return len(self._middlewares) == 0

    def add(self, middleware: Middleware) -> None:
        """Append a middleware to the end of the chain.

        Args:
            middleware: Middleware instance to add.
        """
        self._middlewares.append(middleware)

    async def apply_before_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        step_id: str = "",
        step_description: str = "",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Run before_request for every middleware in declaration order.

        Args:
            messages: List of LLM message dicts.
            tools: List of tool definitions.
            step_id: Current step ID.
            step_description: Current step description.

        Returns:
            (modified_messages, modified_tools).
        """
        request = MiddlewareRequest(
            messages=messages,
            tools=tools,
            step_id=step_id,
            step_description=step_description,
        )
        state: dict[str, Any] = {}
        for mw in self._middlewares:
            request, state = await mw.before_request(request, state)
        return request.messages, request.tools

    async def apply_after_response(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Run after_response for every middleware in declaration order.

        Args:
            content: LLM response content.
            tool_calls: Tool calls from LLM response.
            messages: Messages sent to the LLM.
            tools: Tools available to the LLM.

        Returns:
            (modified_content, modified_tool_calls).
        """
        response = MiddlewareResponse(content=content, tool_calls=tool_calls)
        request = MiddlewareRequest(messages=messages, tools=tools)
        state: dict[str, Any] = {}
        for mw in self._middlewares:
            response, state = await mw.after_response(response, request, state)
        return response.content, response.tool_calls

    async def apply_after_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        error: str | None,
        is_error: bool,
    ) -> ToolCallResult:
        """Run after_tool_call for every middleware in declaration order.

        Args:
            tool_name: Name of the called tool.
            arguments: Arguments passed to the tool.
            output: Tool output string.
            error: Error message if tool failed, else None.
            is_error: Whether the tool call resulted in an error.

        Returns:
            Modified ToolCallResult.
        """
        result = ToolCallResult(
            tool_name=tool_name,
            arguments=arguments,
            output=output,
            error=error,
            is_error=is_error,
        )
        state: dict[str, Any] = {}
        for mw in self._middlewares:
            result, state = await mw.after_tool_call(result, state)
        return result
