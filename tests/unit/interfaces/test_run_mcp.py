"""Tests for run_mcp entry point and the ping health-check tool.

Coverage:
- _build_server: returns WeebotMCPServer, takes its collaborators from one container
- main(): sys.exit(1) on bad settings; calls run_stdio / run_sse correctly
- ping tool: returns JSON with status, version, ISO timestamp
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, create_autospec, patch

import pytest

def _server_mock():
    """A server double whose method signatures match the real class.

    `MagicMock()` with a bare `AsyncMock()` attribute accepts any call, so
    these tests passed while `main()` called `run_sse(host=..., port=...)`
    against a `run_sse(self)` that took neither -- a TypeError in production
    that no test could see. `spec=` does not help: it constrains which
    attributes exist, not how they are called. Only autospec binds the real
    signature.
    """
    from weebot.mcp.server import WeebotMCPServer

    return create_autospec(WeebotMCPServer, instance=True)


# ---------------------------------------------------------------------------
# _build_server: one composition-root container (W5.3)
# ---------------------------------------------------------------------------


class _Container:
    """A container double: `found` maps keys to objects; anything else raises."""

    def __init__(self, found=None, scheduler=None):
        self._found = found or {}
        self._scheduler = scheduler

    def get(self, key):
        if key in self._found:
            return self._found[key]
        raise KeyError(key)

    def build_scheduler(self):
        if self._scheduler is None:
            raise KeyError("scheduler")
        return self._scheduler


class TestBuildServer:
    def test_returns_weebot_mcp_server(self) -> None:
        """_build_server() returns a WeebotMCPServer instance."""
        from run_mcp import _build_server
        from weebot.mcp.server import WeebotMCPServer

        server = _build_server(container=_Container())
        assert isinstance(server, WeebotMCPServer)

    def test_graceful_when_managers_unavailable(self) -> None:
        """Nothing resolves -> the server is still created, without them."""
        from run_mcp import _build_server

        server = _build_server(container=_Container())

        assert server._state_manager is None
        assert server._scheduler is None

    def test_the_container_supplies_every_collaborator(self) -> None:
        """State repo, scheduler, event store and reranker all come from the one
        container. The scheduler used to be imported from a module that does
        not exist (weebot.infrastructure.scheduling), so it was always None."""
        from run_mcp import _build_server
        from weebot.application.ports.event_store_port import EventStorePort
        from weebot.application.ports.rerank_port import RerankPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort

        repo, sched, store, rerank = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        container = _Container(
            {StateRepositoryPort: repo, EventStorePort: store, RerankPort: rerank},
            scheduler=sched,
        )
        server = _build_server(container=container)

        assert server._state_manager is repo and server._scheduler is sched
        assert server._event_store is store and server._rerank is rerank


# ---------------------------------------------------------------------------
# main() — settings validation and transport selection
# ---------------------------------------------------------------------------


class TestMain:
    def test_exits_1_on_missing_api_key(self) -> None:
        """main() calls sys.exit(1) when settings validation fails."""
        from run_mcp import main

        with (
            patch("sys.argv", ["run_mcp.py"]),
            patch(
                "weebot.config.settings.WeebotSettings.validate_at_least_one_key",
                side_effect=ValueError("no keys configured"),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1

    def test_calls_run_stdio_by_default(self) -> None:
        """With no flags, main() calls server.run_stdio()."""
        from run_mcp import main

        mock_server = _server_mock()

        with (
            patch("weebot.config.settings.WeebotSettings.validate_at_least_one_key"),
            patch("run_mcp._build_server", return_value=mock_server),
            patch("sys.argv", ["run_mcp.py"]),
            patch("asyncio.run"),
        ):
            main()

        mock_server.run_stdio.assert_called_once()

    def test_calls_run_sse_with_transport_flag(self) -> None:
        """--transport sse calls server.run_sse()."""
        from run_mcp import main

        mock_server = _server_mock()

        with (
            patch("weebot.config.settings.WeebotSettings.validate_at_least_one_key"),
            patch("run_mcp._build_server", return_value=mock_server),
            patch("sys.argv", ["run_mcp.py", "--transport", "sse"]),
            patch("asyncio.run"),
        ):
            main()

        mock_server.run_sse.assert_called_once()

    def test_rejects_remote_sse_bind_without_opt_in(self) -> None:
        """Non-loopback SSE host is blocked unless explicit opt-in is provided."""
        from run_mcp import main

        with (
            patch("weebot.config.settings.WeebotSettings.validate_at_least_one_key"),
            patch("sys.argv", ["run_mcp.py", "--transport", "sse", "--host", "0.0.0.0"]),
            patch.dict("os.environ", {}, clear=False),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_allows_remote_sse_bind_with_allow_remote_flag(self) -> None:
        """--allow-remote enables explicit non-loopback SSE binding."""
        from run_mcp import main

        mock_server = _server_mock()

        with (
            patch("weebot.config.settings.WeebotSettings.validate_at_least_one_key"),
            patch("run_mcp._build_server", return_value=mock_server),
            patch(
                "sys.argv",
                ["run_mcp.py", "--transport", "sse", "--host", "0.0.0.0", "--allow-remote"],
            ),
            patch.dict("os.environ", {"WEEBOT_MCP_API_KEY": "test-key"}, clear=False),
            patch("asyncio.run"),
        ):
            main()

        mock_server.run_sse.assert_called_once()


# ---------------------------------------------------------------------------
# ping tool
# ---------------------------------------------------------------------------


class TestPingTool:
    @pytest.mark.asyncio
    async def test_ping_returns_ok_status(self) -> None:
        """ping tool returns {"status": "ok", ...}."""
        from mcp.types import CallToolResult
        from weebot.mcp.server import WeebotMCPServer

        server = WeebotMCPServer()
        result = await server.mcp.call_tool("ping", {})
        assert isinstance(result, CallToolResult)
        data = json.loads(result.content[0].text)
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_ping_returns_version(self) -> None:
        """ping response includes 'version' key."""
        from mcp.types import CallToolResult
        from weebot.mcp.server import WeebotMCPServer

        server = WeebotMCPServer()
        result = await server.mcp.call_tool("ping", {})
        assert isinstance(result, CallToolResult)
        data = json.loads(result.content[0].text)
        assert "version" in data

    @pytest.mark.asyncio
    async def test_ping_returns_valid_iso_timestamp(self) -> None:
        """ping 'timestamp' field is a valid ISO 8601 datetime string."""
        from datetime import datetime
        from mcp.types import CallToolResult
        from weebot.mcp.server import WeebotMCPServer

        server = WeebotMCPServer()
        result = await server.mcp.call_tool("ping", {})
        assert isinstance(result, CallToolResult)
        data = json.loads(result.content[0].text)

        assert "timestamp" in data
        # datetime.fromisoformat raises ValueError if the string is not valid ISO 8601
        dt = datetime.fromisoformat(data["timestamp"])
        assert dt is not None

    @pytest.mark.asyncio
    async def test_ping_tool_is_listed_in_tools(self) -> None:
        """ping appears in the list of registered MCP tools."""
        from weebot.mcp.server import WeebotMCPServer

        server = WeebotMCPServer()
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert "ping" in names


def test_build_server_wires_the_tool_and_skill_resources():
    # run_mcp passed no tool_discovery or skill_registry, so weebot://tools and
    # weebot://skills always returned placeholder stubs (F62).
    from run_mcp import _build_server

    server = _build_server()
    assert server._tool_discovery is not None
    assert server._skill_registry is not None and server._skill_registry.list_names()
