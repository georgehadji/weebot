"""ToolExecutor — isolated tool call execution with timeout, hook support, and error handling.

Extracted from ExecutorAgent (weebot/application/agents/executor.py) as part of H1 decomposition.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time as _timer
from typing import Any, Dict, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.models.tool_collection import ToolCollection
from weebot.tools.base import ToolResult


logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tool calls with timeout enforcement, hook support, and error handling.

    Delegates to a ToolCollection for actual tool dispatch. This class handles
    the execution lifecycle: argument parsing, timeout, pre/post hooks, error classification.
    """

    def __init__(
        self,
        tools: ToolCollection,
        hooks: Optional[Any] = None,
        event_bus: Optional[EventBusPort] = None,
    ) -> None:
        self._tools = tools
        self._hooks = hooks
        self._event_bus = event_bus

    async def execute_tool(
        self,
        name: str,
        arguments: str | dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a single tool call with argument parsing and timeout enforcement."""
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
                if not isinstance(args, dict):
                    return ToolResult.error_result(
                        error=f"Invalid tool arguments JSON for '{name}': expected object.",
                        output=f"Invalid tool arguments JSON for '{name}'.",
                        tool_name=name,
                    )
            except json.JSONDecodeError as exc:
                return ToolResult.error_result(
                    error=f"Invalid tool arguments JSON for '{name}': {exc.msg}.",
                    output=f"Invalid tool arguments JSON for '{name}'.",
                    tool_name=name,
                )
        else:
            args = arguments or {}

        tool_obj = self._tools.get_tool(name)
        timeout = float(getattr(tool_obj, "default_timeout_seconds", 60) if tool_obj else 60)
        if "timeout" in args:
            try:
                timeout = min(float(args["timeout"]) + 5.0, 305.0)
            except (ValueError, TypeError):
                pass

        # Pre-tool hook
        if self._hooks is not None:
            await self._hooks.execute_hooks("pre_tool_call", {
                "tool_name": name,
                "tool_args": args,
            })

        _t0 = _timer.monotonic()
        try:
            result = await asyncio.wait_for(
                self._tools.execute(_name=name, **args), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out after %.0fs", name, timeout)
            return ToolResult.error_result(
                error=f"Tool '{name}' timed out after {int(timeout)}s.",
                output=f"Tool '{name}' timed out after {int(timeout)}s.",
                timeout_seconds=timeout,
                tool_name=name,
            )
        _elapsed = (_timer.monotonic() - _t0) * 1000

        # Post-tool hook
        if self._hooks is not None:
            await self._hooks.execute_hooks("post_tool_call", {
                "tool_name": name,
                "tool_args": args,
                "result": result,
                "elapsed_ms": _elapsed,
                "success": not isinstance(result, Exception),
            })
        return result

    async def execute_tool_call(self, tc: Dict[str, Any]) -> ToolResult:
        """Execute a tool call from a structured tool_call dict (function name + arguments)."""
        return await self.execute_tool(
            tc["function"]["name"],
            tc["function"].get("arguments", "{}"),
        )

    async def execute_tool_batch(
        self, tool_calls: list[Dict[str, Any]]
    ) -> list[ToolResult]:
        """Execute a batch of tool calls concurrently and return their results."""
        tasks: list[asyncio.Task[ToolResult]] = []
        for tc in tool_calls:
            tasks.append(asyncio.ensure_future(self.execute_tool_call(tc)))

        raw = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[ToolResult] = []
        for i, r in enumerate(raw):
            if isinstance(r, Exception):
                tc = tool_calls[i]
                t_name = tc["function"]["name"]
                results.append(ToolResult.error_result(
                    error=f"Tool '{t_name}' raised: {r}",
                    tool_name=t_name,
                ))
            else:
                results.append(r)
        return results