"""Tests for WeebotMCPServer (Phase 5 — MCP Server Integration).

Coverage:
- Resource builder pure functions (resources.py)
- WeebotMCPServer construction and properties
- Tool registration (list_tools)
- Resource registration (list_resources)
- MCP tool calls with mocked underlying tools
- Activity stream logging after tool calls
- MCP resource reads
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, patch

from weebot.activity_stream import ActivityStream
from weebot.mcp.resources import build_activity_json, build_schedule_json, build_state_json
from weebot.mcp.server import WeebotMCPServer
from weebot.tools.base import ToolResult


# ─── Resource builder unit tests (no MCP protocol) ───────────────────────────


class TestResourceBuilders:
    """Pure unit tests for resources.py data-builder functions."""

    def test_build_activity_json_empty_stream(self) -> None:
        stream = ActivityStream()
        data = json.loads(build_activity_json(stream))
        assert data == []

    def test_build_activity_json_events_newest_first(self) -> None:
        stream = ActivityStream()
        stream.push("proj1", "tool", "first event")
        stream.push("proj2", "job", "second event")
        data = json.loads(build_activity_json(stream, n=10))
        # ActivityStream.push uses appendleft → newest is at index 0
        assert data[0]["message"] == "second event"
        assert data[1]["message"] == "first event"

    def test_build_activity_json_has_required_keys(self) -> None:
        stream = ActivityStream()
        stream.push("p", "k", "msg")
        data = json.loads(build_activity_json(stream))
        event = data[0]
        assert {"project_id", "kind", "message", "timestamp"} <= event.keys()

    def test_build_state_json_has_status_key(self) -> None:
        data = json.loads(build_state_json())
        assert "status" in data
        assert data["status"] == "idle"

    def test_build_schedule_json_has_jobs_list(self) -> None:
        data = json.loads(build_schedule_json())
        assert "jobs" in data
        assert isinstance(data["jobs"], list)


# ─── Server construction ──────────────────────────────────────────────────────


class TestWeebotMCPServerConstruction:
    """WeebotMCPServer is created correctly and wires its dependencies."""

    def test_server_name_is_weebot(self) -> None:
        server = WeebotMCPServer()
        assert server.mcp.name == "weebot"

    def test_server_accepts_custom_activity_stream(self) -> None:
        stream = ActivityStream()
        server = WeebotMCPServer(activity_stream=stream)
        assert server._activity is stream

    def test_server_creates_default_activity_stream_when_none(self) -> None:
        server = WeebotMCPServer()
        assert isinstance(server._activity, ActivityStream)

    @pytest.mark.asyncio
    async def test_exposes_all_four_tools(self) -> None:
        server = WeebotMCPServer()
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert {"bash", "python_execute", "web_search", "file_editor"} <= names

    @pytest.mark.asyncio
    async def test_exposes_three_resources(self) -> None:
        server = WeebotMCPServer()
        resources = await server.mcp.list_resources()
        uris = {str(r.uri) for r in resources}
        assert uris == {"weebot://activity", "weebot://state", "weebot://schedule"}


# ─── MCP tool call tests ──────────────────────────────────────────────────────


class TestMCPToolCalls:
    """Verify tool wrappers pass results through the MCP protocol correctly."""

    @pytest.mark.asyncio
    async def test_bash_success_returns_output(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.bash_tool.BashTool.execute",
            new=AsyncMock(return_value=ToolResult(output="hello from bash")),
        ):
            content, _ = await server.mcp.call_tool("bash", {"command": "echo hello"})
        assert any("hello from bash" in item.text for item in content)

    @pytest.mark.asyncio
    async def test_bash_error_raises_tool_error(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.bash_tool.BashTool.execute",
            new=AsyncMock(return_value=ToolResult(output="", error="Command denied by policy")),
        ):
            with pytest.raises(Exception, match="Command denied"):
                await server.mcp.call_tool("bash", {"command": "format c:"})

    @pytest.mark.asyncio
    async def test_python_execute_returns_stdout(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.python_tool.PythonExecuteTool.execute",
            new=AsyncMock(return_value=ToolResult(output="42\n")),
        ):
            content, _ = await server.mcp.call_tool("python_execute", {"code": "print(6*7)"})
        assert any("42" in item.text for item in content)

    @pytest.mark.asyncio
    async def test_web_search_returns_results(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.web_search.WebSearchTool.execute",
            new=AsyncMock(return_value=ToolResult(output="Result 1: Python asyncio guide")),
        ):
            content, _ = await server.mcp.call_tool("web_search", {"query": "python asyncio"})
        assert any("Result" in item.text for item in content)

    @pytest.mark.asyncio
    async def test_bash_logs_to_activity_stream(self) -> None:
        stream = ActivityStream()
        server = WeebotMCPServer(activity_stream=stream)
        with patch(
            "weebot.tools.bash_tool.BashTool.execute",
            new=AsyncMock(return_value=ToolResult(output="ok")),
        ):
            await server.mcp.call_tool("bash", {"command": "echo hi"})
        events = stream.recent()
        assert any("bash:" in e.message for e in events)


# ─── MCP resource read tests ──────────────────────────────────────────────────


class TestMCPResourceReads:
    """Verify resource handlers return correct JSON via the MCP protocol."""

    @pytest.mark.asyncio
    async def test_activity_resource_returns_json_list(self) -> None:
        stream = ActivityStream()
        stream.push("proj1", "tool", "test event for MCP")
        server = WeebotMCPServer(activity_stream=stream)
        contents = await server.mcp.read_resource("weebot://activity")
        data = json.loads(contents[0].content)
        assert isinstance(data, list)
        assert any(e["message"] == "test event for MCP" for e in data)

    @pytest.mark.asyncio
    async def test_activity_resource_is_newest_first(self) -> None:
        stream = ActivityStream()
        stream.push("p", "k", "older")
        stream.push("p", "k", "newer")
        server = WeebotMCPServer(activity_stream=stream)
        contents = await server.mcp.read_resource("weebot://activity")
        data = json.loads(contents[0].content)
        assert data[0]["message"] == "newer"

    @pytest.mark.asyncio
    async def test_state_resource_has_status_key(self) -> None:
        server = WeebotMCPServer()
        contents = await server.mcp.read_resource("weebot://state")
        data = json.loads(contents[0].content)
        assert "status" in data

    @pytest.mark.asyncio
    async def test_schedule_resource_has_jobs_list(self) -> None:
        server = WeebotMCPServer()
        contents = await server.mcp.read_resource("weebot://schedule")
        data = json.loads(contents[0].content)
        assert "jobs" in data
        assert isinstance(data["jobs"], list)


# ─── Fix 1: stub response when state_manager / scheduler omitted ──────────────


class TestResourceStubNotes:
    """Stubs include a helpful 'note' when managers are not provided."""

    def test_state_stub_contains_note(self) -> None:
        data = json.loads(build_state_json(state_manager=None))
        assert "note" in data

    def test_schedule_stub_contains_note(self) -> None:
        data = json.loads(build_schedule_json(scheduler=None))
        assert "note" in data


# ─── Fix 2: settings-driven default timeout ───────────────────────────────────


class TestSettingsTimeout:
    """BashTool and PythonExecuteTool respect WeebotSettings timeouts."""

    def test_bash_tool_stores_default_timeout_from_settings(self) -> None:
        from unittest.mock import patch
        from weebot.tools.bash_tool import BashTool

        # WeebotSettings is imported locally inside model_post_init, so we patch
        # the class in its home module (weebot.config.settings).
        with patch(
            "weebot.config.settings.WeebotSettings",
            return_value=type(
                "S",
                (),
                {"bash_timeout": 42, "sandbox_max_output_bytes": 65_536},
            )(),
        ):
            tool = BashTool()
        assert tool._default_timeout == 42.0

    def test_python_tool_stores_default_timeout_from_settings(self) -> None:
        from unittest.mock import patch
        from weebot.tools.python_tool import PythonExecuteTool

        with patch(
            "weebot.config.settings.WeebotSettings",
            return_value=type(
                "S",
                (),
                {"python_timeout": 55, "sandbox_max_output_bytes": 65_536},
            )(),
        ):
            tool = PythonExecuteTool()
        assert tool._default_timeout == 55.0

    @pytest.mark.asyncio
    async def test_bash_execute_uses_explicit_timeout_over_default(self) -> None:
        """Explicit timeout= kwarg overrides the settings default."""
        from unittest.mock import AsyncMock, patch
        from weebot.tools.bash_tool import BashTool
        from weebot.sandbox.executor import ExecutionResult

        captured: list[float] = []

        async def fake_run(cmd, timeout=30.0, **kw):  # type: ignore[override]
            captured.append(timeout)
            return ExecutionResult(stdout="ok", stderr="", returncode=0, elapsed_ms=1)

        tool = BashTool()
        with patch.object(tool._executor, "run", side_effect=fake_run):
            await tool.execute(command="echo hi", timeout=99.0)

        assert captured == [99.0]


# ─── Fix 3: live data when managers are provided ──────────────────────────────


class TestLiveResources:
    """State and schedule resources return live data when managers provided."""

    def test_state_json_with_state_manager_returns_projects(self) -> None:
        mock_sm = type(
            "SM",
            (),
            {
                "list_projects": lambda self: [
                    {"project_id": "p1", "status": "active"},
                    {"project_id": "p2", "status": "completed"},
                ]
            },
        )()
        data = json.loads(build_state_json(state_manager=mock_sm))
        assert data["total_projects"] == 2
        assert data["active_projects"] == 1
        assert data["status"] == "active"

    def test_state_json_no_active_projects_reports_idle(self) -> None:
        mock_sm = type(
            "SM",
            (),
            {
                "list_projects": lambda self: [
                    {"project_id": "p1", "status": "completed"}
                ]
            },
        )()
        data = json.loads(build_state_json(state_manager=mock_sm))
        assert data["status"] == "idle"

    def test_schedule_json_with_scheduler_returns_jobs(self) -> None:
        class FakeJob:
            def to_dict(self):
                return {"job_id": "j1", "name": "backup", "status": "active"}

        mock_sched = type(
            "Sched", (), {"list_jobs": lambda self: [FakeJob()]}
        )()
        data = json.loads(build_schedule_json(scheduler=mock_sched))
        assert data["total"] == 1
        assert data["jobs"][0]["job_id"] == "j1"

    def test_schedule_json_error_in_scheduler_returns_empty_jobs(self) -> None:
        mock_sched = type(
            "Sched",
            (),
            {"list_jobs": lambda self: (_ for _ in ()).throw(RuntimeError("db error"))},
        )()
        data = json.loads(build_schedule_json(scheduler=mock_sched))
        assert data["jobs"] == []
        assert "error" in data

    @pytest.mark.asyncio
    async def test_server_passes_state_manager_to_resource(self) -> None:
        mock_sm = type(
            "SM",
            (),
            {"list_projects": lambda self: [{"project_id": "live", "status": "active"}]},
        )()
        server = WeebotMCPServer(state_manager=mock_sm)
        contents = await server.mcp.read_resource("weebot://state")
        data = json.loads(contents[0].content)
        assert data["total_projects"] == 1
        assert data["status"] == "active"
