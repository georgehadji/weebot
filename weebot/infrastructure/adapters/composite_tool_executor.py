"""CompositeToolExecutor — runs composite tool sub-calls via a dispatcher."""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from weebot.domain.models.composite_tool import (
    CompositeResult,
    CompositeToolSpec,
    CompositeToolResultLike,
)

logger = logging.getLogger(__name__)

# Pre-compiled regex for ${var} substitution inside composite argument templates.
_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


class CompositeToolExecutor:
    """Executes composite tool sub-calls through an async dispatcher.

    The dispatcher is a mapping of tool name to an async callable.  This keeps
    the executor independent of ``weebot.tools`` and ``BackendPort`` internals;
    the MCP server supplies callables that invoke the registered tool handlers.
    """

    def __init__(
        self,
        dispatcher: dict[str, Callable[..., Awaitable[Any]]] | None = None,
    ) -> None:
        self._dispatcher = dict(dispatcher or {})
        self._captured: dict[str, str] = {}

    def set_dispatcher(
        self,
        dispatcher: dict[str, Callable[..., Awaitable[Any]]],
    ) -> None:
        """Replace the tool dispatcher (used when tools are registered lazily)."""
        self._dispatcher = dict(dispatcher)

    async def execute(
        self,
        spec: CompositeToolSpec,
        runtime_args: dict[str, Any] | None = None,
    ) -> CompositeResult:
        """Run all sub-tools serially and return a summary result.

        Args:
            spec: Composite tool specification.
            runtime_args: Optional arguments supplied by the MCP client that
                override values in each step's argument template.
        """
        self._captured.clear()
        runtime_args = runtime_args or {}
        sub_results: list[dict[str, Any]] = []

        for step in spec.sub_tools:
            handler = self._dispatcher.get(step.tool_name)
            if handler is None:
                error = f"Composite step '{step.tool_name}' is not available"
                sub_results.append({
                    "tool": step.tool_name,
                    "success": False,
                    "output": "",
                    "error": error,
                })
                return CompositeResult(
                    success=False,
                    summary=f"Composite {spec.name} failed: {error}",
                    sub_results=sub_results,
                    aborted_after_failure=False,
                )

            args = dict(step.arguments)
            args.update({k: v for k, v in runtime_args.items() if k in args})
            args = self._resolve_args(args)
            try:
                raw = await handler(**args)
            except Exception as exc:  # pragma: no cover - defensive
                raw = _ErrorLike(str(exc))

            result = _as_result_like(raw)
            sub_results.append({
                "tool": step.tool_name,
                "success": not result.is_error,
                "output": result.output,
                "error": result.error,
            })

            if result.is_error:
                if spec.transaction_policy == "all_or_none":
                    return CompositeResult(
                        success=False,
                        summary=f"Step {step.tool_name} failed: {result.error}",
                        sub_results=sub_results,
                        aborted_after_failure=True,
                    )
                # best_effort: continue to next step

            if step.capture_output_as:
                self._captured[step.capture_output_as] = result.output

        summary = self._build_summary(sub_results)
        all_success = all(r["success"] for r in sub_results)
        return CompositeResult(
            success=all_success,
            summary=summary,
            sub_results=sub_results,
            aborted_after_failure=False,
        )

    def _resolve_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Replace ``${var}`` references inside string values with captured outputs."""
        def _replace_vars(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            return _VAR_PATTERN.sub(
                lambda m: self._captured.get(m.group(1), m.group(0)),
                value,
            )

        return {key: _replace_vars(value) for key, value in args.items()}

    @staticmethod
    def _build_summary(sub_results: list[dict[str, Any]]) -> str:
        """Build a concise human-readable summary of sub-tool results."""
        lines = []
        for result in sub_results:
            prefix = "✓" if result["success"] else "✗"
            output = (result.get("output") or "")[:200]
            lines.append(f"{prefix} {result['tool']}: {output}")
        return "\n".join(lines)


class _ErrorLike:
    """Fallback result-like object for exceptions."""

    def __init__(self, message: str) -> None:
        self.is_error = True
        self.output = ""
        self.error = message


def _as_result_like(obj: Any) -> CompositeToolResultLike:
    """Coerce *obj* into the minimal result-like protocol.

    Supports plain dicts (MCP-style error content), objects with ``is_error``,
    and string outputs.
    """
    if isinstance(obj, dict):
        is_error = bool(obj.get("isError") or obj.get("is_error"))
        content = obj.get("content", [])
        text = ""
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text", item)) for item in content if item
            )
        elif isinstance(content, str):
            text = content
        output = text if not is_error else ""
        error = text if is_error else obj.get("error")
        return _ResultLike(output=output, error=error)

    if hasattr(obj, "is_error"):
        return obj

    # Plain string output
    return _ResultLike(output=str(obj), error=None)


class _ResultLike:
    """Simple result-like wrapper."""

    def __init__(self, output: str, error: str | None) -> None:
        self.is_error = bool(error)
        self.output = output
        self.error = error
