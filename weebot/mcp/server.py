"""WeebotMCPServer — exposes weebot tools and resources over MCP (FastMCP).

Transport options:
- stdio: ``await server.run_stdio()``  — for Claude Desktop
- SSE:   ``await server.run_sse()``    — for Claude IDE / web clients
"""
from __future__ import annotations

import os
from collections.abc import Callable

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import CallToolResult, TextContent
except ImportError as _mcp_err:
    raise ImportError(
        "weebot.mcp requires the 'mcp' package. "
        "Install it with:  pip install 'mcp>=1.5'"
    ) from _mcp_err

from weebot.application.services.composite_tool_builder import CompositeToolBuilder
from weebot.core.activity_stream import ActivityStream
from weebot.mcp.resources import (
    build_activity_json,
    build_costs_json,
    build_roadmap_json,
    build_schedule_json,
    build_skills_json,
    build_state_json,
    build_tools_json,
)
from weebot.utils.rate_limiter import check_rate_limit

# Prometheus metrics — lazy import to avoid circular dependency at module level
_metrics = None


def _get_metrics():
    global _metrics
    if _metrics is None:
        from weebot.infrastructure.observability import metrics as _m
        _metrics = _m
    return _metrics

class _APIKeyTokenVerifier:
    """Simple Bearer-token verifier that checks against a static API key.

    Implements the ``TokenVerifier`` protocol expected by FastMCP so that
    the SSE/HTTP transport rejects unauthenticated requests.
    """

    def __init__(self, api_key: str) -> None:
        self._expected = api_key

    async def verify_token(self, token: str) -> bool:
        """Return True if *token* matches the configured API key."""
        return token == self._expected


_SERVER_INSTRUCTIONS = (
    "weebot is an AI Agent Framework for Windows 11. "
    "Available tools: bash (PowerShell/WSL2), python_execute (sandboxed subprocess), "
    "web_search (DuckDuckGo + Bing), file_view, file_create, file_str_replace, "
    "file_insert (view/create/edit files), ping (health check — returns server status and "
    "UTC timestamp). "
    "Available resources: weebot://activity (recent events), "
    "weebot://state (agent state snapshot), weebot://schedule (scheduled jobs), "
    "weebot://products (product requirements roadmap)."
)


class WeebotMCPServer:
    """MCP server that exposes weebot tools and resources via FastMCP.

    Args:
        activity_stream: Optional shared ActivityStream for logging tool calls.
                         A new empty stream is created if not provided.
        state_manager:   Optional :class:`~weebot.application.ports.state_repo_port.StateRepositoryPort`
                         instance.  When provided ``weebot://state`` returns
                         live project data instead of a static stub.
        scheduler:       Optional :class:`~weebot.scheduling.scheduler.SchedulingManager`
                         instance.  When provided ``weebot://schedule`` returns
                         live job data instead of a static stub.
        host: Bind address for SSE/HTTP transport. Default: ``127.0.0.1``.
        port: Port for SSE/HTTP transport. Default: ``8765``.
    """

    def __init__(
        self,
        activity_stream: ActivityStream | None = None,
        state_manager: object | None = None,
        scheduler: object | None = None,
        product_db_path: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        dynamic_tools: list | None = None,
        tool_discovery: object | None = None,
        cascade_tracker: object | None = None,
        skill_registry: object | None = None,
        api_key: str | None = None,
        composite_registry: object | None = None,
        composite_executor: object | None = None,
        composite_tools_enabled: bool = True,
    ) -> None:
        self._activity: ActivityStream = activity_stream or ActivityStream()
        self._state_manager = state_manager
        self._scheduler = scheduler
        self._product_db_path = product_db_path
        self._dynamic_tools = dynamic_tools or []
        self._tool_discovery = tool_discovery
        self._cascade_tracker = cascade_tracker
        self._skill_registry = skill_registry
        self._composite_registry = composite_registry or self._default_composite_registry()
        self._composite_executor = composite_executor or self._default_composite_executor()
        self._composite_tools_enabled = composite_tools_enabled
        # API key for SSE/HTTP transport auth.
        # Falls back to WEEBOT_MCP_API_KEY env var; None = no auth (backward compat).
        self._api_key = api_key or os.environ.get("WEEBOT_MCP_API_KEY")
        # Build a FastMCP TokenVerifier if an API key is set.
        _token_verifier = None
        if self._api_key:
            _token_verifier = _APIKeyTokenVerifier(self._api_key)
        self._mcp: FastMCP = FastMCP(
            "weebot",
            instructions=_SERVER_INSTRUCTIONS,
            host=host,
            port=port,
            token_verifier=_token_verifier,
        )
        if self._api_key:
            import logging
            logging.getLogger(__name__).info(
                "MCP server auth enabled (API key from %s)",
                "explicit param" if api_key else "WEEBOT_MCP_API_KEY env var",
            )
        self._register_tools()
        self._register_dynamic_tools()
        self._register_resources()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def mcp(self) -> FastMCP:
        """The underlying FastMCP instance (for advanced customisation)."""
        return self._mcp

    async def run_stdio(self) -> None:
        """Run the server over stdio (for Claude Desktop)."""
        await self._mcp.run_stdio_async()

    async def run_sse(self) -> None:
        """Run the server over SSE/HTTP (for Claude IDE / web clients)."""
        await self._mcp.run_sse_async()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    @staticmethod
    def _default_composite_registry():
        """Return a default CompositeToolRegistry."""
        from weebot.application.services.composite_tool_registry import (
            CompositeToolRegistry,
        )
        return CompositeToolRegistry()

    @staticmethod
    def _default_composite_executor():
        """Return a default CompositeToolExecutor."""
        from weebot.infrastructure.adapters.composite_tool_executor import (
            CompositeToolExecutor,
        )
        return CompositeToolExecutor()

    @staticmethod
    def _tool_error_response(error: str) -> CallToolResult:
        """Return MCP-compliant structured error content for a tool failure."""
        return CallToolResult(
            content=[TextContent(type="text", text=error)],
            isError=True,
        )

    @staticmethod
    def _tool_success_response(output: str) -> CallToolResult:
        """Return MCP-compliant structured success content for a tool call."""
        return CallToolResult(
            content=[TextContent(type="text", text=output)],
            isError=False,
        )

    def _register_dynamic_tools(self) -> None:
        """Register tools supplied via MCPToolkitAdapter or other dynamic sources."""
        for tool in self._dynamic_tools:
            wrapper = self._wrap_base_tool(tool)
            self._mcp.add_tool(
                wrapper,
                name=tool.name,
                description=tool.description,
            )

    @staticmethod
    def _wrap_base_tool(tool):
        """Wrap a weebot BaseTool so it can be registered with FastMCP.

        Returns MCP-compliant structured error content on failure instead of
        raising an exception, so the client LLM can reason about retry/escalation.
        """
        async def wrapper(**kwargs) -> CallToolResult:
            result = await tool.execute(**kwargs)
            if result.is_error:
                return CallToolResult(
                    content=[
                        TextContent(type="text", text=result.error or "Tool execution failed")
                    ],
                    isError=True,
                )
            return WeebotMCPServer._tool_success_response(result.output)
        return wrapper

    def _register_tools(self) -> None:
        mcp = self._mcp
        activity = self._activity

        # Instantiate tools once — avoids re-parsing .env on every MCP call.
        from weebot.tools.bash_tool import BashTool
        from weebot.tools.python_tool import PythonExecuteTool
        from weebot.tools.web_search import WebSearchTool
        from weebot.tools.file_editor import StrReplaceEditorTool

        _bash_tool = BashTool()
        _python_tool = PythonExecuteTool()
        _search_tool = WebSearchTool()

        # Inject reranker into WebSearchTool if available
        try:
            from weebot.application.di import Container
            from weebot.application.ports.rerank_port import RerankPort
            c = Container()
            c.configure_defaults()
            rerank = c._maybe_get(RerankPort)
            if rerank is not None:
                _search_tool.set_rerank(rerank)
        except Exception:
            import logging as _log
            _log.getLogger(__name__).debug(
                "RerankPort not configured — search results use engine order", exc_info=True
            )

        _editor = StrReplaceEditorTool()

        # ------------------------------------------------------------------
        # Atomic tool handlers
        # ------------------------------------------------------------------
        async def _bash(
            command: str,
            timeout: float = 30.0,
            working_dir: str | None = None,
            use_wsl: bool = False,
        ) -> CallToolResult:
            import time as _time
            allowed, retry_after = check_rate_limit("bash")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool="bash").inc()
                return self._tool_error_response(
                    f"Rate limit exceeded for bash; retry after {retry_after}s"
                )

            _t0 = _time.monotonic()
            try:
                result = await _bash_tool.execute(
                    command=command, timeout=timeout, working_dir=working_dir, use_wsl=use_wsl
                )
            finally:
                _get_metrics().tool_call_duration_seconds.labels(tool="bash").observe(
                    _time.monotonic() - _t0
                )
            activity.push("mcp", "tool", f"bash: {command[:60]}")
            success = not result.is_error
            _get_metrics().tool_calls_total.labels(tool="bash", success=str(success)).inc()
            if result.is_error:
                return self._tool_error_response(result.error or "bash execution failed")
            return self._tool_success_response(result.output)

        async def _python_execute(code: str, timeout: float = 30.0) -> CallToolResult:
            import time as _time
            allowed, retry_after = check_rate_limit("python_execute")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool="python_execute").inc()
                return self._tool_error_response(
                    f"Rate limit exceeded for python_execute; retry after {retry_after}s"
                )

            _t0 = _time.monotonic()
            try:
                result = await _python_tool.execute(code=code, timeout=timeout)
            finally:
                _get_metrics().tool_call_duration_seconds.labels(tool="python_execute").observe(
                    _time.monotonic() - _t0
                )
            activity.push("mcp", "tool", f"python_execute: {code[:60]}")
            success = not result.is_error
            _get_metrics().tool_calls_total.labels(
                tool="python_execute", success=str(success)
            ).inc()
            if result.is_error:
                return self._tool_error_response(result.error or "python execution failed")
            return self._tool_success_response(result.output)

        async def _web_search(query: str, num_results: int = 5) -> CallToolResult:
            import time as _time
            allowed, retry_after = check_rate_limit("web_search")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool="web_search").inc()
                return self._tool_error_response(
                    f"Rate limit exceeded for web_search; retry after {retry_after}s"
                )

            _t0 = _time.monotonic()
            try:
                result = await _search_tool.execute(query=query, num_results=num_results)
            finally:
                _get_metrics().tool_call_duration_seconds.labels(tool="web_search").observe(
                    _time.monotonic() - _t0
                )
            activity.push("mcp", "tool", f"web_search: {query[:60]}")
            success = not result.is_error
            _get_metrics().tool_calls_total.labels(tool="web_search", success=str(success)).inc()
            if result.is_error:
                return self._tool_error_response(result.error or "web search failed")
            return self._tool_success_response(result.output)

        async def _run_file_tool(tool_name: str, **kwargs) -> CallToolResult:
            """Shared helper for file tools: rate limit, execute, metrics, errors."""
            import time as _time

            allowed, retry_after = check_rate_limit("file_editor")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool=tool_name).inc()
                return self._tool_error_response(
                    f"Rate limit exceeded for {tool_name}; retry after {retry_after}s"
                )

            _t0 = _time.monotonic()
            try:
                result = await _editor.execute(**kwargs)
            finally:
                _get_metrics().tool_call_duration_seconds.labels(tool=tool_name).observe(
                    _time.monotonic() - _t0
                )
            activity.push(
                "mcp",
                "tool",
                f"{tool_name}: {kwargs.get('command')} {kwargs.get('path', '')[:40]}",
            )
            success = not result.is_error
            _get_metrics().tool_calls_total.labels(tool=tool_name, success=str(success)).inc()
            if result.is_error:
                return self._tool_error_response(result.error or f"{tool_name} failed")
            return self._tool_success_response(result.output)

        async def _file_view(path: str, view_range: list[int] | None = None) -> CallToolResult:
            return await _run_file_tool(
                "file_view", command="view", path=path, view_range=view_range
            )

        async def _file_create(path: str, file_text: str) -> CallToolResult:
            return await _run_file_tool(
                "file_create", command="create", path=path, file_text=file_text
            )

        async def _file_str_replace(path: str, old_str: str, new_str: str) -> CallToolResult:
            return await _run_file_tool(
                "file_str_replace",
                command="str_replace",
                path=path,
                old_str=old_str,
                new_str=new_str,
            )

        async def _file_insert(path: str, insert_line: int, new_str: str) -> CallToolResult:
            return await _run_file_tool(
                "file_insert",
                command="insert",
                path=path,
                insert_line=insert_line,
                new_str=new_str,
            )

        async def _file_editor_legacy(
            command: str,
            path: str,
            file_text: str | None = None,
            old_str: str | None = None,
            new_str: str | None = None,
            insert_line: int | None = None,
        ) -> CallToolResult:
            kwargs: dict = {"command": command, "path": path}
            if file_text is not None:
                kwargs["file_text"] = file_text
            if old_str is not None:
                kwargs["old_str"] = old_str
            if new_str is not None:
                kwargs["new_str"] = new_str
            if insert_line is not None:
                kwargs["insert_line"] = insert_line
            return await _run_file_tool("file_editor", **kwargs)

        async def _ping_tool() -> CallToolResult:
            import json as _json
            from datetime import datetime, timezone

            return self._tool_success_response(
                _json.dumps(
                    {
                        "status": "ok",
                        "version": "1.0.0",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

        # ------------------------------------------------------------------
        # Build the tool catalog and dispatcher
        # ------------------------------------------------------------------
        tool_specs: list[tuple[str, str, Callable[..., object]]] = [
            (
                "bash",
                (
                    "Execute a shell command via PowerShell (Windows) or WSL2 bash. "
                    "Dangerous commands are blocked; destructive commands require confirmation. "
                    "Rate limited: 10 burst, 2/second sustained."
                ),
                _bash,
            ),
            (
                "python_execute",
                (
                    "Execute Python code in a sandboxed subprocess. "
                    "Returns combined stdout and stderr. Dangerous code is blocked by policy. "
                    "Rate limited: 5 burst, 1/second sustained."
                ),
                _python_execute,
            ),
            (
                "web_search",
                (
                    "Search the web using DuckDuckGo (Bing fallback). "
                    "Returns titles, URLs, and snippets for the top results. "
                    "Rate limited: 5 burst, 0.5/second sustained."
                ),
                _web_search,
            ),
            (
                "file_view",
                (
                    "Read a file or list a directory. "
                    "Returns numbered file contents or directory listing. "
                    "Use 'view_range' to read a partial range [start, end]."
                ),
                _file_view,
            ),
            (
                "file_create",
                "Create a new file with the given content. Fails if the file already exists.",
                _file_create,
            ),
            (
                "file_str_replace",
                (
                    "Replace a specific string in a file with new text. "
                    "old_str must match exactly. Use file_view first to read the file."
                ),
                _file_str_replace,
            ),
            (
                "file_insert",
                (
                    "Insert lines at a specific position in a file. "
                    "insert_line=0 means before line 1."
                ),
                _file_insert,
            ),
            (
                "file_editor",
                (
                    "DEPRECATED: Use file_view, file_create, file_str_replace, "
                    "or file_insert instead. Kept for backward compatibility "
                    "with legacy MCP clients."
                ),
                _file_editor_legacy,
            ),
            (
                "ping",
                (
                    "Health check — returns server status and current UTC timestamp. "
                    "Use this to verify that the weebot MCP server is running and reachable."
                ),
                _ping_tool,
            ),
        ]

        # Dispatcher used by composite tools to invoke atomic tools internally.
        dispatcher: dict[str, Callable[..., object]] = {
            name: handler for name, _, handler in tool_specs
        }

        # ------------------------------------------------------------------
        # Composite tools (H2) — register first so the registry knows which
        # atomic tools to hide before we expose the atomic catalog.
        # ------------------------------------------------------------------
        if self._composite_tools_enabled and self._composite_registry is not None:
            if self._composite_executor is not None:
                self._composite_executor.set_dispatcher(dispatcher)
            self._register_composite_tools(dispatcher)

        # Register visible atomic tools.
        for name, description, handler in tool_specs:
            if (
                self._composite_registry is not None
                and not self._composite_registry.is_visible(name)
            ):
                continue
            mcp.add_tool(handler, name=name, description=description)

    def _register_composite_tools(
        self,
        dispatcher: dict[str, Callable[..., object]],
    ) -> None:
        """Register composite workflow tools and hide covered atomics."""
        from weebot.mcp.composite_tools import DEFAULT_COMPOSITE_TOOLS

        mcp = self._mcp
        registry = self._composite_registry
        executor = self._composite_executor

        if registry is None or executor is None:
            return

        builder = CompositeToolBuilder()
        for spec in DEFAULT_COMPOSITE_TOOLS:
            registry.register(spec)
            handler = builder.build(spec, executor.execute)
            mcp.add_tool(handler, name=spec.name, description=spec.description)

    # ------------------------------------------------------------------
    # Resource registration
    # ------------------------------------------------------------------

    def _register_resources(self) -> None:
        mcp = self._mcp
        activity = self._activity
        state_manager = self._state_manager
        scheduler = self._scheduler
        product_db_path = self._product_db_path
        tool_discovery = self._tool_discovery
        cascade_tracker = self._cascade_tracker
        skill_registry = self._skill_registry

        @mcp.resource(
            "weebot://skills",
            mime_type="application/json",
            description="Installed skills with descriptions, versions, and triggers.",
        )
        def skills_resource() -> str:
            return build_skills_json(skill_registry)

        @mcp.resource(
            "weebot://activity",
            mime_type="application/json",
            description="Recent agent activity events (newest-first, up to 50).",
        )
        def activity_stream_resource() -> str:
            return build_activity_json(activity)

        @mcp.resource(
            "weebot://state",
            mime_type="application/json",
            description="Current weebot agent state snapshot.",
        )
        def state_resource() -> str:
            return build_state_json(state_manager)

        @mcp.resource(
            "weebot://schedule",
            mime_type="application/json",
            description="List of currently scheduled jobs.",
        )
        def schedule_resource() -> str:
            return build_schedule_json(scheduler)

        @mcp.resource(
            "weebot://products",
            mime_type="application/json",
            description="Product requirements roadmap grouped by project and category.",
        )
        def products_resource() -> str:
            return build_roadmap_json(product_db_path)

        @mcp.resource(
            "weebot://tools",
            mime_type="application/json",
            description=(
                "Available agent tools with role access, safety flags, and "
                "dependency requirements.  Returns all tools across all roles."
            ),
        )
        async def tools_resource() -> str:
            return await build_tools_json(tool_discovery, role=None)

        @mcp.resource(
            "weebot://costs",
            mime_type="application/json",
            description=(
                "Current-session cost and model cascade statistics. "
                "Includes per-tier success/failure/circuit_open counts, "
                "total cost estimate, cascade hit rate, and recent decisions."
            ),
        )
        def costs_resource() -> str:
            return build_costs_json(cascade_tracker)

        @mcp.resource(
            "weebot://routing",
            mime_type="application/json",
            description=(
                "ACR routing analytics — per-category model selection "
                "distribution, success rates, latency, and budget usage."
            ),
        )
        def routing_resource() -> str:
            from weebot.mcp.resources import build_routing_json
            return build_routing_json(
                cascade_tracker=cascade_tracker,
            )
