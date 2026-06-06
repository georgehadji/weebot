"""WeebotMCPServer — exposes weebot tools and resources over MCP (FastMCP).

Transport options:
- stdio: ``await server.run_stdio()``  — for Claude Desktop
- SSE:   ``await server.run_sse()``    — for Claude IDE / web clients
"""
from __future__ import annotations

from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _mcp_err:
    raise ImportError(
        "weebot.mcp requires the 'mcp' package. "
        "Install it with:  pip install 'mcp>=1.5'"
    ) from _mcp_err

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
from weebot.utils.rate_limiter import RateLimitExceeded, check_rate_limit

# Prometheus metrics — lazy import to avoid circular dependency at module level
_metrics = None


def _get_metrics():
    global _metrics
    if _metrics is None:
        from weebot.infrastructure.observability import metrics as _m
        _metrics = _m
    return _metrics

_SERVER_INSTRUCTIONS = (
    "weebot is an AI Agent Framework for Windows 11. "
    "Available tools: bash (PowerShell/WSL2), python_execute (sandboxed subprocess), "
    "web_search (DuckDuckGo + Bing), file_editor (view/create/edit files), "
    "ping (health check — returns server status and UTC timestamp). "
    "Available resources: weebot://activity (recent events), "
    "weebot://state (agent state snapshot), weebot://schedule (scheduled jobs), "
    "weebot://products (product requirements roadmap)."
)


class WeebotMCPServer:
    """MCP server that exposes weebot tools and resources via FastMCP.

    Args:
        activity_stream: Optional shared ActivityStream for logging tool calls.
                         A new empty stream is created if not provided.
        state_manager:   Optional :class:`~weebot.state_manager.StateManager`
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
        activity_stream: Optional[ActivityStream] = None,
        state_manager: Optional[object] = None,
        scheduler: Optional[object] = None,
        product_db_path: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        dynamic_tools: Optional[list] = None,
        tool_discovery: Optional[object] = None,
        cascade_tracker: Optional[object] = None,
        skill_registry: Optional[object] = None,
    ) -> None:
        self._activity: ActivityStream = activity_stream or ActivityStream()
        self._state_manager = state_manager
        self._scheduler = scheduler
        self._product_db_path = product_db_path
        self._dynamic_tools = dynamic_tools or []
        self._tool_discovery = tool_discovery
        self._cascade_tracker = cascade_tracker
        self._skill_registry = skill_registry
        self._mcp: FastMCP = FastMCP(
            "weebot",
            instructions=_SERVER_INSTRUCTIONS,
            host=host,
            port=port,
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
        """Wrap a weebot BaseTool so it can be registered with FastMCP."""
        async def wrapper(**kwargs):
            result = await tool.execute(**kwargs)
            if result.is_error:
                raise ValueError(result.error)
            return result.output
        return wrapper

    def _register_tools(self) -> None:
        mcp = self._mcp
        activity = self._activity

        # Instantiate tools once — avoids re-parsing .env on every MCP call.
        from weebot.tools.bash_tool import BashTool
        from weebot.tools.python_tool import PythonExecuteTool
        from weebot.tools.web_search import WebSearchTool
        from weebot.tools.file_editor import StrReplaceEditorTool

        _bash = BashTool()
        _python = PythonExecuteTool()
        _search = WebSearchTool()
        _editor = StrReplaceEditorTool()

        @mcp.tool(
            name="bash",
            description=(
                "Execute a shell command via PowerShell (Windows) or WSL2 bash. "
                "Dangerous commands are blocked; destructive commands require confirmation. "
                "Rate limited: 10 burst, 2/second sustained."
            ),
        )
        async def bash(
            command: str,
            timeout: float = 30.0,
            working_dir: str | None = None,
            use_wsl: bool = False,
        ) -> str:
            import time as _time
            # Rate limit check
            allowed, retry_after = check_rate_limit("bash")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool="bash").inc()
                raise RateLimitExceeded("bash", retry_after)

            _t0 = _time.monotonic()
            try:
                result = await _bash.execute(
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
                raise ValueError(result.error)
            return result.output

        @mcp.tool(
            name="python_execute",
            description=(
                "Execute Python code in a sandboxed subprocess. "
                "Returns combined stdout and stderr. Dangerous code is blocked by policy. "
                "Rate limited: 5 burst, 1/second sustained."
            ),
        )
        async def python_execute(code: str, timeout: float = 30.0) -> str:
            import time as _time
            # Rate limit check
            allowed, retry_after = check_rate_limit("python_execute")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool="python_execute").inc()
                raise RateLimitExceeded("python_execute", retry_after)

            _t0 = _time.monotonic()
            try:
                result = await _python.execute(code=code, timeout=timeout)
            finally:
                _get_metrics().tool_call_duration_seconds.labels(tool="python_execute").observe(
                    _time.monotonic() - _t0
                )
            activity.push("mcp", "tool", f"python_execute: {code[:60]}")
            success = not result.is_error
            _get_metrics().tool_calls_total.labels(tool="python_execute", success=str(success)).inc()
            if result.is_error:
                raise ValueError(result.error)
            return result.output

        @mcp.tool(
            name="web_search",
            description=(
                "Search the web using DuckDuckGo (Bing fallback). "
                "Returns titles, URLs, and snippets for the top results. "
                "Rate limited: 5 burst, 0.5/second sustained."
            ),
        )
        async def web_search(query: str, num_results: int = 5) -> str:
            import time as _time
            # Rate limit check
            allowed, retry_after = check_rate_limit("web_search")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool="web_search").inc()
                raise RateLimitExceeded("web_search", retry_after)

            _t0 = _time.monotonic()
            try:
                result = await _search.execute(query=query, num_results=num_results)
            finally:
                _get_metrics().tool_call_duration_seconds.labels(tool="web_search").observe(
                    _time.monotonic() - _t0
                )
            activity.push("mcp", "tool", f"web_search: {query[:60]}")
            success = not result.is_error
            _get_metrics().tool_calls_total.labels(tool="web_search", success=str(success)).inc()
            if result.is_error:
                raise ValueError(result.error)
            return result.output

        @mcp.tool(
            name="file_editor",
            description=(
                "View, create, or edit files on the local filesystem. "
                "Commands: view (read file or list dir), create (write new file), "
                "str_replace (find-and-replace), insert (add lines at position). "
                "Rate limited: 20 burst, 5/second sustained."
            ),
        )
        async def file_editor(
            command: str,
            path: str,
            file_text: str | None = None,
            old_str: str | None = None,
            new_str: str | None = None,
            insert_line: int | None = None,
        ) -> str:
            import time as _time
            # Rate limit check
            allowed, retry_after = check_rate_limit("file_editor")
            if not allowed:
                _get_metrics().mcp_rate_limits_hit_total.labels(tool="file_editor").inc()
                raise RateLimitExceeded("file_editor", retry_after)

            kwargs: dict = {}
            if file_text is not None:
                kwargs["file_text"] = file_text
            if old_str is not None:
                kwargs["old_str"] = old_str
            if new_str is not None:
                kwargs["new_str"] = new_str
            if insert_line is not None:
                kwargs["insert_line"] = insert_line
            _t0 = _time.monotonic()
            try:
                result = await _editor.execute(command=command, path=path, **kwargs)
            finally:
                _get_metrics().tool_call_duration_seconds.labels(tool="file_editor").observe(
                    _time.monotonic() - _t0
                )
            activity.push("mcp", "tool", f"file_editor: {command} {path[:40]}")
            success = not result.is_error
            _get_metrics().tool_calls_total.labels(tool="file_editor", success=str(success)).inc()
            if result.is_error:
                raise ValueError(result.error)
            return result.output

        @mcp.tool(
            name="ping",
            description=(
                "Health check — returns server status and current UTC timestamp. "
                "Use this to verify that the weebot MCP server is running and reachable."
            ),
        )
        async def ping_tool() -> str:
            import json as _json
            from datetime import datetime, timezone

            return _json.dumps(
                {
                    "status": "ok",
                    "version": "1.0.0",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

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
                "dependency requirements.  Supports ?role= filter query param "
                "(e.g. weebot://tools?role=researcher)."
            ),
        )
        async def tools_resource() -> str:
            # FastMCP passes query params as kwargs when the resource is called
            # with a URI like weebot://tools?role=admin
            return await build_tools_json(tool_discovery)

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
