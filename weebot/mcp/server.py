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

from weebot.activity_stream import ActivityStream
from weebot.mcp.resources import (
    build_activity_json,
    build_roadmap_json,
    build_schedule_json,
    build_state_json,
)

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
    ) -> None:
        self._activity: ActivityStream = activity_stream or ActivityStream()
        self._state_manager = state_manager
        self._scheduler = scheduler
        self._product_db_path = product_db_path
        self._mcp: FastMCP = FastMCP(
            "weebot",
            instructions=_SERVER_INSTRUCTIONS,
            host=host,
            port=port,
        )
        self._register_tools()
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
                "Dangerous commands are blocked; destructive commands require confirmation."
            ),
        )
        async def bash(
            command: str,
            timeout: float = 30.0,
            working_dir: str | None = None,
            use_wsl: bool = False,
        ) -> str:
            result = await _bash.execute(
                command=command, timeout=timeout, working_dir=working_dir, use_wsl=use_wsl
            )
            activity.push("mcp", "tool", f"bash: {command[:60]}")
            if result.is_error:
                raise ValueError(result.error)
            return result.output

        @mcp.tool(
            name="python_execute",
            description=(
                "Execute Python code in a sandboxed subprocess. "
                "Returns combined stdout and stderr. Dangerous code is blocked by policy."
            ),
        )
        async def python_execute(code: str, timeout: float = 30.0) -> str:
            result = await _python.execute(code=code, timeout=timeout)
            activity.push("mcp", "tool", f"python_execute: {code[:60]}")
            if result.is_error:
                raise ValueError(result.error)
            return result.output

        @mcp.tool(
            name="web_search",
            description=(
                "Search the web using DuckDuckGo (Bing fallback). "
                "Returns titles, URLs, and snippets for the top results."
            ),
        )
        async def web_search(query: str, num_results: int = 5) -> str:
            result = await _search.execute(query=query, num_results=num_results)
            activity.push("mcp", "tool", f"web_search: {query[:60]}")
            if result.is_error:
                raise ValueError(result.error)
            return result.output

        @mcp.tool(
            name="file_editor",
            description=(
                "View, create, or edit files on the local filesystem. "
                "Commands: view (read file or list dir), create (write new file), "
                "str_replace (find-and-replace), insert (add lines at position)."
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
            kwargs: dict = {}
            if file_text is not None:
                kwargs["file_text"] = file_text
            if old_str is not None:
                kwargs["old_str"] = old_str
            if new_str is not None:
                kwargs["new_str"] = new_str
            if insert_line is not None:
                kwargs["insert_line"] = insert_line
            result = await _editor.execute(command=command, path=path, **kwargs)
            activity.push("mcp", "tool", f"file_editor: {command} {path[:40]}")
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
