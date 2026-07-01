"""ToolCollection — registry and dispatcher for tools.

Promoted from weebot.tools.base to the application layer because
ToolCollection is a pure orchestration concept with no hard
infrastructure dependencies.  It imports BaseTool/ToolResult from
the tools layer as the stable tool contract.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from weebot.application.services.tool_call_repair import fuzzy_match_tool_name
from weebot.config.constants import MAX_TOOL_OUTPUT_CHARS


# ── Phase 4: Strategy-aware output truncation ─────────────────────
def _truncate(output: str, limit: int, strategy: str) -> str:
    """Truncate *output* to *limit* chars using *strategy*.

    Strategies:
        "head"     — keep the beginning (default, current behavior).
        "tail"     — keep the end (for shell output where errors appear last).
        "boundary" — truncate at the last complete record boundary
                     (newline or JSON object boundary).

    Returns the truncated string with a "[N chars omitted]" sentinel.
    """
    if len(output) <= limit:
        return output
    removed = len(output) - limit
    sentinel = f"\n...[{removed} chars omitted]"

    if strategy == "tail":
        return sentinel + output[-limit:]

    if strategy == "boundary":
        # Find last complete record boundary within limit
        chunk = output[:limit]
        boundary = max(chunk.rfind("\n"), chunk.rfind("}, "), chunk.rfind("}\n"), chunk.rfind(", "))
        if boundary > limit // 2:
            removed = len(output) - boundary
            return output[:boundary] + f"\n...[{removed} chars omitted]"
        return chunk + f"\n...[{removed} chars omitted]"

    # "head" (default)
    return output[:limit] + f"\n...[{removed} chars omitted]"

from weebot.tools.base import BaseTool, ToolResult

# Phase 5: Optional result cache (lazy import to avoid circular deps)
_cache_module = None
def _get_cache():
    global _cache_module
    if _cache_module is None:
        try:
            from weebot.application.services.tool_result_cache import ToolResultCache as _c
            _cache_module = _c
        except Exception as _exc:
            logger.warning("ToolResultCache unavailable — caching disabled: %s", _exc)
            _cache_module = False
    return _cache_module if _cache_module is not False else None

# Prometheus metrics — lazy import to avoid hard infrastructure coupling
_metrics_module = None


from weebot.application.services.metrics_bridge import get_metrics as _get_tool_metrics


class ToolCollection:
    """Registry of tools; dispatches execute() by name."""

    # Phase 1: Retry defaults for transient tool failures
    DEFAULT_MAX_RETRIES: int = 2
    RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
        OSError, TimeoutError, ConnectionError,
    )

    def __init__(self, *tools: BaseTool, canonicalizer=None, contract_loader=None, cache=None) -> None:
        self._tools: dict[str, BaseTool] = {t.name: t for t in tools}
        # Action Canonicalizer (Tier 1.1) — validates + corrects tool calls
        self._canonicalizer = canonicalizer
        # Environment Contract DSL (Tier 3.2) — enhances tool descriptions
        self._contract_loader = contract_loader
        # Phase 3: Health check cache (None = not yet checked)
        self._healthy: dict[str, bool] | None = None
        # Phase 5: Optional result cache (session-scoped)
        self._cache = cache

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def get_tool(self, name: str) -> BaseTool | None:
        """Look up a tool by name. Returns None if not found."""
        return self._tools.get(name)

    async def teardown(self) -> None:
        """Shut down all tools that expose a shutdown() coroutine.

        Call this when the session or executor that owns this collection ends,
        so that tools backed by external service connections (e.g. ApifyService
        aiohttp sessions) can release their resources cleanly.
        """
        for tool in self._tools.values():
            svc = getattr(tool, "apify_service", None)
            if svc is not None and callable(getattr(svc, "shutdown", None)):
                try:
                    await svc.shutdown()
                except Exception:
                    logger.debug("Error shutting down service for tool %r", tool.name, exc_info=True)

    async def check_health(self) -> dict[str, bool]:
        """Run health checks for all tools; cache results for this session.

        Returns a dict of tool_name -> health_status.
        """
        results = await asyncio.gather(
            *[t.health_check() for t in self._tools.values()],
            return_exceptions=True,
        )
        self._healthy = {
            name: (r is True)
            for name, r in zip(self._tools.keys(), results)
        }
        return dict(self._healthy)

    def to_params(self) -> list[dict]:
        params = []
        for tool in self._tools.values():
            # Phase 3: Skip tools that failed health check (if check has run)
            if self._healthy is not None and not self._healthy.get(tool.name, True):
                continue
            spec = tool.to_param()
            # Inject contract pitfalls into description if available (Tier 3.2)
            if self._contract_loader is not None:
                enhanced = self._contract_loader.enhance_description(
                    tool.name, spec["function"]["description"]
                )
                spec["function"]["description"] = enhanced
            params.append(spec)
        return params

    async def execute(self, _name: str, **kwargs: Any) -> ToolResult:
        if _name not in self._tools:
            # Try fuzzy name match before giving up (handles typos, casing)
            fuzzy_name = fuzzy_match_tool_name(_name, list(self._tools.keys()))
            if fuzzy_name is not None:
                _name = fuzzy_name
            else:
                return ToolResult.error_result(
                    error=f"Unknown tool: {_name!r}",
                    execution_time_ms=0.0,
                    retry_count=0,
                )

        # Phase 3: Block execution of unhealthy tools (if health check has run)
        if self._healthy is not None and not self._healthy.get(_name, True):
            return ToolResult.error_result(
                error=f"Tool '{_name}' is unavailable (health check failed). "
                      "Its runtime dependencies may not be installed.",
                execution_time_ms=0.0,
                retry_count=0,
                tool_name=_name,
            )

        # ── Tier 1.1: Action Canonicalizer — validate + correct before dispatch ──
        if self._canonicalizer is not None:
            result = self._canonicalizer.canonicalize(_name, kwargs)
            if result.verdict == "block":
                return ToolResult.error_result(
                    error=result.block_reason or f"Blocked by canonicalizer for '{_name}'",
                    execution_time_ms=0.0,
                    retry_count=0,
                )
            if result.changes:
                kwargs = result.corrected_args

        # Phase 2: Per-tool concurrency semaphore
        tool_obj = self._tools.get(_name)
        limit = getattr(tool_obj, "max_concurrent", 0) if tool_obj else 0

        # Phase 5: Cache lookup (before execution)
        if self._cache is not None:
            cached = self._cache.get(_name, kwargs)
            if cached is not None:
                cached.metadata["cache_hit"] = True
                cached.metadata.setdefault("tool_name", _name)
                return cached

        # Phase 2: Lazy semaphore for concurrency-capped tools
        _tool_semaphore = None
        if limit > 0:
            if not hasattr(self, '_semaphores'):
                self._semaphores: dict[str, asyncio.Semaphore] = {}
            if _name not in self._semaphores:
                self._semaphores[_name] = asyncio.Semaphore(limit)
            _tool_semaphore = self._semaphores[_name]

        start_time = time.time()
        retry_count = 0
        max_retries = kwargs.pop("_max_retries", self.DEFAULT_MAX_RETRIES)

        async def _execute_with_semaphore():
            if _tool_semaphore is not None:
                async with _tool_semaphore:
                    return await self._tools[_name].execute(**kwargs)
            return await self._tools[_name].execute(**kwargs)

        while True:
            try:
                result = await _execute_with_semaphore()

                # Add execution metadata
                execution_time_ms = (time.time() - start_time) * 1000
                result.metadata.update(
                    {
                        "execution_time_ms": execution_time_ms,
                        "retry_count": retry_count,
                        "tool_name": _name,
                    }
                )

                # Phase 4: Strategy-aware truncation to prevent context window bloat
                tool_obj = self._tools.get(_name)
                strategy = getattr(tool_obj, "truncation_strategy", "head")
                if result.output and len(result.output) > MAX_TOOL_OUTPUT_CHARS:
                    original_length = len(result.output)
                    result.output = _truncate(result.output, MAX_TOOL_OUTPUT_CHARS, strategy)
                    result.metadata["truncated"] = True
                    result.metadata["original_length"] = original_length
                    result.metadata["truncation_strategy"] = strategy
                else:
                    result.metadata.setdefault("truncated", False)

                # Tool metrics (best-effort)
                m = _get_tool_metrics()
                if m is not None:
                    try:
                        m.tool_calls_total.labels(tool=_name, success="true").inc()
                    except Exception:
                        logger.debug("Failed to increment tool call metric for %s", _name, exc_info=True)

                # Phase 5: Cache store (after successful execution)
                if self._cache is not None and not result.is_error:
                    self._cache.set(_name, kwargs, result)

                return result

            except Exception as exc:
                # Log the full traceback before discarding it
                logger.exception("Tool %s raised an unhandled exception", _name)

                # Phase 1: Only retry on transient/retryable exceptions.
                # Non-retryable errors (ValueError, TypeError, etc.) surface
                # immediately to avoid masking logic bugs.
                if not isinstance(exc, self.RETRYABLE_EXCEPTIONS):
                    execution_time_ms = (time.time() - start_time) * 1000
                    return ToolResult.error_result(
                        error=str(exc),
                        execution_time_ms=execution_time_ms,
                        retry_count=0,
                        tool_name=_name,
                    )

                # Tool failure metric (best-effort)
                m = _get_tool_metrics()
                if m is not None:
                    try:
                        m.tool_calls_total.labels(tool=_name, success="false").inc()
                    except Exception:
                        logger.debug("Failed to increment tool error metric for %s", _name, exc_info=True)

                retry_count += 1

                if retry_count > max_retries:
                    execution_time_ms = (time.time() - start_time) * 1000
                    return ToolResult.error_result(
                        error=str(exc),
                        execution_time_ms=execution_time_ms,
                        retry_count=retry_count - 1,
                        tool_name=_name,
                    )

                # Capped exponential backoff before retry
                await asyncio.sleep(min(0.1 * (2 ** retry_count), 5.0))
