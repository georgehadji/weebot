"""Tests for run_mcp entry point and the ping health-check tool.

Coverage:
- _try_attach: returns None on import failure, instance on success
- _build_server: returns WeebotMCPServer, forwards managers
- main(): sys.exit(1) on bad settings; calls run_stdio / run_sse correctly
- ping tool: returns JSON with status, version, ISO timestamp
"""
from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _try_attach
# ---------------------------------------------------------------------------


class TestTryAttach:
    def test_returns_none_on_import_error(self) -> None:
        """Missing module → None, no exception raised."""
        from run_mcp import _try_attach

        result = _try_attach("weebot.does_not_exist_xyz", "SomeClass", "Test")
        assert result is None

    def test_returns_instance_on_success(self) -> None:
        """Existing class → instantiated object returned."""
        from run_mcp import _try_attach
        from weebot.activity_stream import ActivityStream

        result = _try_attach("weebot.activity_stream", "ActivityStream", "ActivityStream")
        assert isinstance(result, ActivityStream)


# ---------------------------------------------------------------------------
# _build_server
# ---------------------------------------------------------------------------


class TestBuildServer:
    def test_returns_weebot_mcp_server(self) -> None:
        """_build_server() returns a WeebotMCPServer instance."""
        from run_mcp import _build_server
        from weebot.mcp.server import WeebotMCPServer

        server = _build_server()
        assert isinstance(server, WeebotMCPServer)

    def test_graceful_when_managers_unavailable(self) -> None:
        """All _try_attach calls returning None → server still created."""
        from run_mcp import _build_server

        with patch("run_mcp._try_attach", return_value=None):
            server = _build_server()

        assert server._state_manager is None
        assert server._scheduler is None

    def test_attaches_state_manager_when_available(self) -> None:
        """A non-None return from _try_attach is forwarded to the server."""
        from run_mcp import _build_server

        mock_sm = MagicMock()

        def fake_attach(module_path: str, class_name: str, label: str):
            if class_name == "StateManager":
                return mock_sm
            return None

        with patch("run_mcp._try_attach", side_effect=fake_attach):
            server = _build_server()

        assert server._state_manager is mock_sm


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

        mock_server = MagicMock()
        mock_server.run_stdio = AsyncMock()

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

        mock_server = MagicMock()
        mock_server.run_sse = AsyncMock()

        with (
            patch("weebot.config.settings.WeebotSettings.validate_at_least_one_key"),
            patch("run_mcp._build_server", return_value=mock_server),
            patch("sys.argv", ["run_mcp.py", "--transport", "sse"]),
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
        from weebot.mcp.server import WeebotMCPServer

        server = WeebotMCPServer()
        content, _ = await server.mcp.call_tool("ping", {})
        data = json.loads(content[0].text)
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_ping_returns_version(self) -> None:
        """ping response includes 'version' key."""
        from weebot.mcp.server import WeebotMCPServer

        server = WeebotMCPServer()
        content, _ = await server.mcp.call_tool("ping", {})
        data = json.loads(content[0].text)
        assert "version" in data

    @pytest.mark.asyncio
    async def test_ping_returns_valid_iso_timestamp(self) -> None:
        """ping 'timestamp' field is a valid ISO 8601 datetime string."""
        from datetime import datetime
        from weebot.mcp.server import WeebotMCPServer

        server = WeebotMCPServer()
        content, _ = await server.mcp.call_tool("ping", {})
        data = json.loads(content[0].text)

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
