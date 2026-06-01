"""ToolCollection — registry and dispatcher for tools.

Promoted from weebot.tools.base to the application layer because
ToolCollection is a pure orchestration concept with no hard
infrastructure dependencies.  It imports BaseTool/ToolResult from
the tools layer as the stable tool contract.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from weebot.config.constants import MAX_TOOL_OUTPUT_CHARS
from weebot.tools.base import BaseTool, ToolResult

# Prometheus metrics — lazy import to avoid hard infrastructure coupling
_metrics_module = None


def _get_tool_metrics():
    global _metrics_module
    if _metrics_module is None:
        try:
            from weebot.infrastructure.observability import metrics as m
            _metrics_module = m
        except Exception:
            _metrics_module = False  # sentinel — metrics unavailable
    return _metrics_module if _metrics_module is not False else None


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
        if name not in self._tools:
            return ToolResult.error_result(
                error=f"Unknown tool: {name!r}",
                execution_time_ms=0.0,
                retry_count=0,
            )

        start_time = time.time()
        retry_count = 0
        max_retries = kwargs.pop("_max_retries", 0)

        while True:
            try:
                result = await self._tools[name].execute(**kwargs)

                # Add execution metadata
                execution_time_ms = (time.time() - start_time) * 1000
                result.metadata.update(
                    {
                        "execution_time_ms": execution_time_ms,
                        "retry_count": retry_count,
                        "tool_name": name,
                    }
                )

                # Truncate oversized output to prevent context window bloat
                if result.output and len(result.output) > MAX_TOOL_OUTPUT_CHARS:
                    original_length = len(result.output)
                    removed = original_length - MAX_TOOL_OUTPUT_CHARS
                    result.output = (
                        result.output[:MAX_TOOL_OUTPUT_CHARS]
                        + f"\n...[truncated: {removed} chars omitted]"
                    )
                    result.metadata["truncated"] = True
                    result.metadata["original_length"] = original_length
                else:
                    result.metadata.setdefault("truncated", False)

                # Tool metrics (best-effort)
                m = _get_tool_metrics()
                if m is not None:
                    try:
                        m.tool_calls_total.labels(tool=name, success="true").inc()
                    except Exception:
                        pass

                return result

            except Exception as exc:
                # Tool failure metric (best-effort)
                m = _get_tool_metrics()
                if m is not None:
                    try:
                        m.tool_calls_total.labels(tool=name, success="false").inc()
                    except Exception:
                        pass

                retry_count += 1

                if retry_count > max_retries:
                    execution_time_ms = (time.time() - start_time) * 1000
                    return ToolResult.error_result(
                        error=str(exc),
                        execution_time_ms=execution_time_ms,
                        retry_count=retry_count - 1,
                        tool_name=name,
                    )

                # Simple backoff before retry
                await asyncio.sleep(0.1 * retry_count)
