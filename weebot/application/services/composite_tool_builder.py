"""CompositeToolBuilder — constructs FastMCP-compatible composite handlers.

Moves the inline handler/signature construction out of ``weebot.mcp.server``
so composite tool behavior can be unit-tested without starting a full MCP
server.
"""
from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from mcp.types import CallToolResult, TextContent
except ImportError as _mcp_err:  # pragma: no cover - optional dependency
    raise ImportError(
        "CompositeToolBuilder requires the 'mcp' package. "
        "Install it with:  pip install 'mcp>=1.5'"
    ) from _mcp_err

from weebot.domain.models.composite_tool import CompositeToolSpec

# Matches ``${var_name}`` references inside composite argument templates.
_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


CompositeExecutorLike = Callable[
    [CompositeToolSpec, dict[str, Any]],
    Awaitable[Any],
]
"""Minimal callable used by the builder to execute a composite spec.

The executor receives the spec and the runtime arguments supplied by the MCP
client, and returns a result-like object with at least ``success`` and
``summary`` attributes.  This keeps the builder decoupled from the concrete
``CompositeToolExecutor`` infrastructure adapter.
"""


class CompositeToolBuilder:
    """Build a FastMCP-compatible async callable from a CompositeToolSpec."""

    def build(
        self,
        spec: CompositeToolSpec,
        executor: CompositeExecutorLike,
    ) -> Callable[..., Awaitable[CallToolResult]]:
        """Build an async handler for *spec* using *executor*.

        Args:
            spec: Composite tool specification (sub-tools, captures, etc.).
            executor: Callable that runs the composite and returns a result with
                ``success`` and ``summary`` attributes.

        Returns:
            An async callable with a dynamically-built ``inspect.Signature``
            exposing only the runtime arguments required by the spec.
        """
        runtime_args = self._extract_runtime_args(spec)
        params = [
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
            )
            for name in sorted(runtime_args)
        ]
        signature = inspect.Signature(params)

        async def _composite_handler(**kwargs: Any) -> CallToolResult:
            try:
                result = await executor(spec, runtime_args=kwargs)
            except Exception as exc:  # pragma: no cover - defensive
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))],
                    isError=True,
                )

            if not getattr(result, "success", False):
                return CallToolResult(
                    content=[TextContent(type="text", text=getattr(result, "summary", ""))],
                    isError=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=getattr(result, "summary", ""))],
                isError=False,
            )

        _composite_handler.__name__ = spec.name
        _composite_handler.__signature__ = signature  # type: ignore[attr-defined]
        _composite_handler.__doc__ = spec.description
        return _composite_handler

    @staticmethod
    def _extract_runtime_args(spec: CompositeToolSpec) -> set[str]:
        """Return runtime argument names referenced by ``${var}`` templates.

        Captured outputs (``capture_output_as``) are excluded because they are
        populated internally by the executor, not supplied by the MCP client.
        """
        captured: set[str] = set()
        runtime_args: set[str] = set()
        for step in spec.sub_tools:
            for value in step.arguments.values():
                if isinstance(value, str):
                    for var in _VAR_PATTERN.findall(value):
                        if var not in captured:
                            runtime_args.add(var)
            if step.capture_output_as:
                captured.add(step.capture_output_as)
        return runtime_args
