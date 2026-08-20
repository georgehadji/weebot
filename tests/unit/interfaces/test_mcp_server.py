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
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import CallToolResult

from weebot.core.activity_stream import ActivityStream
from weebot.mcp.resources import (
    build_activity_json,
    build_roadmap_json,
    build_schedule_json,
    build_state_json,
)
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
    async def test_exposes_core_tools(self) -> None:
        server = WeebotMCPServer()
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert {"bash", "python_execute"} <= names

    @pytest.mark.asyncio
    async def test_exposes_decomposed_file_tools(self) -> None:
        server = WeebotMCPServer()
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        expected = {"file_view", "file_create", "file_str_replace", "file_insert"}
        assert expected <= names

    @pytest.mark.asyncio
    async def test_exposes_core_resources(self) -> None:
        server = WeebotMCPServer()
        resources = await server.mcp.list_resources()
        uris = {str(r.uri) for r in resources}
        assert {
            "weebot://activity",
            "weebot://state",
            "weebot://schedule",
            "weebot://products",
        } <= uris

    @pytest.mark.asyncio
    async def test_exposes_composite_tools(self) -> None:
        server = WeebotMCPServer()
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert "analyze_and_edit" in names
        assert "research_and_summarize" in names

    @pytest.mark.asyncio
    async def test_composite_tools_hide_covered_atomics(self) -> None:
        server = WeebotMCPServer()
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        # analyze_and_edit hides file_editor; research_and_summarize hides web_search
        assert "file_editor" not in names
        assert "web_search" not in names

    @pytest.mark.asyncio
    async def test_composite_tools_disabled_restores_atomics(self) -> None:
        server = WeebotMCPServer(composite_tools_enabled=False)
        tools = await server.mcp.list_tools()
        names = {t.name for t in tools}
        assert "file_editor" in names
        assert "web_search" in names
        assert "analyze_and_edit" not in names


class TestMCPToolCalls:
    """Verify tool wrappers pass results through the MCP protocol correctly."""

    @pytest.mark.asyncio
    async def test_bash_success_returns_output(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.bash_tool.BashTool.execute",
            new=AsyncMock(return_value=ToolResult(output="hello from bash")),
        ):
            result = await server.mcp.call_tool("bash", {"command": "echo hello"})
        assert isinstance(result, CallToolResult)
        assert not result.isError
        assert any("hello from bash" in item.text for item in result.content)

    @pytest.mark.asyncio
    async def test_bash_error_returns_structured_error(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.bash_tool.BashTool.execute",
            new=AsyncMock(return_value=ToolResult(output="", error="Command denied by policy")),
        ):
            result = await server.mcp.call_tool("bash", {"command": "format c:"})
        assert isinstance(result, CallToolResult)
        assert result.isError
        assert any("Command denied" in item.text for item in result.content)

    @pytest.mark.asyncio
    async def test_python_execute_returns_stdout(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.python_tool.PythonExecuteTool.execute",
            new=AsyncMock(return_value=ToolResult(output="42\n")),
        ):
            result = await server.mcp.call_tool("python_execute", {"code": "print(6*7)"})
        assert isinstance(result, CallToolResult)
        assert not result.isError
        assert any("42" in item.text for item in result.content)

    @pytest.mark.asyncio
    async def test_python_execute_error_returns_structured_error(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.python_tool.PythonExecuteTool.execute",
            new=AsyncMock(return_value=ToolResult(output="", error="SyntaxError")),
        ):
            result = await server.mcp.call_tool("python_execute", {"code": "bad syntax"})
        assert isinstance(result, CallToolResult)
        assert result.isError

    @pytest.mark.asyncio
    async def test_web_search_returns_results(self) -> None:
        # Disable composites so the atomic web_search tool is exposed.
        server = WeebotMCPServer(composite_tools_enabled=False)
        with patch(
            "weebot.tools.web_search.WebSearchTool.execute",
            new=AsyncMock(return_value=ToolResult(output="Result 1: Python asyncio guide")),
        ):
            result = await server.mcp.call_tool("web_search", {"query": "python asyncio"})
        assert isinstance(result, CallToolResult)
        assert not result.isError
        assert any("Result" in item.text for item in result.content)

    @pytest.mark.asyncio
    async def test_file_view_returns_numbered_lines(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.file_editor.StrReplaceEditorTool.execute",
            new=AsyncMock(return_value=ToolResult(output="1 | hello\n2 | world")),
        ):
            result = await server.mcp.call_tool("file_view", {"path": "test.txt"})
        assert isinstance(result, CallToolResult)
        assert not result.isError
        assert any("hello" in item.text for item in result.content)

    @pytest.mark.asyncio
    async def test_file_create_writes_new_file(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.file_editor.StrReplaceEditorTool.execute",
            new=AsyncMock(return_value=ToolResult(output="created test.txt")),
        ):
            result = await server.mcp.call_tool(
                "file_create", {"path": "test.txt", "file_text": "hello"}
            )
        assert isinstance(result, CallToolResult)
        assert not result.isError

    @pytest.mark.asyncio
    async def test_file_str_replace_requires_old_str(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.file_editor.StrReplaceEditorTool.execute",
            new=AsyncMock(return_value=ToolResult(output="replaced")),
        ):
            result = await server.mcp.call_tool(
                "file_str_replace", {"path": "test.txt", "old_str": "hello", "new_str": "hi"}
            )
        assert isinstance(result, CallToolResult)
        assert not result.isError

    @pytest.mark.asyncio
    async def test_file_editor_legacy_still_works(self) -> None:
        # Disable composites so the legacy file_editor tool is exposed.
        server = WeebotMCPServer(composite_tools_enabled=False)
        with patch(
            "weebot.tools.file_editor.StrReplaceEditorTool.execute",
            new=AsyncMock(return_value=ToolResult(output="legacy result")),
        ):
            result = await server.mcp.call_tool(
                "file_editor", {"command": "view", "path": "test.txt"}
            )
        assert isinstance(result, CallToolResult)
        assert not result.isError
        assert any("legacy result" in item.text for item in result.content)

    @pytest.mark.asyncio
    async def test_file_view_error_returns_structured_error(self) -> None:
        server = WeebotMCPServer()
        with patch(
            "weebot.tools.file_editor.StrReplaceEditorTool.execute",
            new=AsyncMock(return_value=ToolResult(output="", error="file not found")),
        ):
            result = await server.mcp.call_tool("file_view", {"path": "missing.txt"})
        assert isinstance(result, CallToolResult)
        assert result.isError

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

    @pytest.mark.asyncio
    async def test_composite_analyze_and_edit_runs_sub_tools(self) -> None:
        server = WeebotMCPServer()
        with (
            patch(
                "weebot.tools.file_editor.StrReplaceEditorTool.execute",
                new=AsyncMock(
                    side_effect=[ToolResult(output="1 | old line"), ToolResult(output="replaced")]
                ),
            ),
            patch(
                "weebot.tools.python_tool.PythonExecuteTool.execute",
                new=AsyncMock(return_value=ToolResult(output="syntax ok")),
            ),
        ):
            result = await server.mcp.call_tool(
                "analyze_and_edit",
                {"path": "test.txt", "old_str": "old line", "new_str": "new line"},
            )
        assert isinstance(result, CallToolResult)
        assert not result.isError
        assert any("file_str_replace" in item.text for item in result.content)


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
        data = json.loads(build_state_json(state_repo=None))
        assert "note" in data

    def test_schedule_stub_contains_note(self) -> None:
        data = json.loads(build_schedule_json(scheduler=None))
        assert "note" in data


# ─── Fix 2: settings-driven default timeout ───────────────────────────────────


class TestSettingsTimeout:
    """BashTool and PythonExecuteTool respect WeebotSettings timeouts."""

    def test_bash_tool_stores_default_timeout_from_settings(self) -> None:
        from weebot.tools.bash_tool import BashTool
        from weebot.config.tool_config import ToolConfig

        tool = BashTool()
        tool.set_config(ToolConfig(bash_timeout=42))
        assert tool._default_timeout == 42.0

    def test_python_tool_stores_default_timeout_from_settings(self) -> None:
        from weebot.tools.python_tool import PythonExecuteTool
        from weebot.config.tool_config import ToolConfig

        tool = PythonExecuteTool()
        tool.set_config(ToolConfig(python_timeout=55))
        assert tool._default_timeout == 55.0

    @pytest.mark.asyncio
    async def test_bash_execute_uses_explicit_timeout_over_default(self) -> None:
        """Explicit timeout= kwarg overrides the settings default."""
        from weebot.tools.bash_tool import BashTool
        from weebot.application.ports.sandbox_port import SandboxResult, SandboxPort

        captured: list[float] = []

        from weebot.application.ports.sandbox_port import SandboxType

        class FakeSandbox(SandboxPort):
            @property
            def sandbox_type(self):
                return SandboxType.NATIVE

            async def is_available(self):
                return True

            def get_capabilities(self):
                return set()

            async def execute(
                self, command, timeout=None, cwd=None, env=None, memory_limit_mb=None
            ):
                return SandboxResult(stdout="", stderr="", returncode=0, elapsed_ms=1)

            async def execute_shell(self, script, shell="bash", timeout=30.0, cwd=None, **kw):
                captured.append(timeout)
                return SandboxResult(stdout="ok", stderr="", returncode=0, elapsed_ms=1)

            async def execute_python(self, code, timeout=30.0, **kw):
                return SandboxResult(stdout="", stderr="", returncode=0, elapsed_ms=1)

        tool = BashTool(sandbox=FakeSandbox())
        await tool.execute(command="echo hi", timeout=99.0)

        assert captured == [99.0]


# ─── Fix 3: live data when managers are provided ──────────────────────────────


class TestLiveResources:
    """State and schedule resources return live data when managers provided."""

    def test_state_json_with_state_manager_returns_projects(self) -> None:
        from weebot.domain.models.session import SessionStatus

        session1 = type("S", (), {"session_id": "p1", "status": SessionStatus.RUNNING})()
        session2 = type("S", (), {"session_id": "p2", "status": SessionStatus.COMPLETED})()
        mock_repo = type(
            "Repo", (), {"list_sessions": AsyncMock(return_value=[session1, session2])}
        )()
        data = json.loads(build_state_json(state_repo=mock_repo))
        assert data["total_sessions"] == 2
        assert data["active_sessions"] == 1
        assert data["status"] == "active"

    def test_state_json_no_active_projects_reports_idle(self) -> None:
        from weebot.domain.models.session import SessionStatus

        session1 = type("S", (), {"session_id": "p1", "status": SessionStatus.COMPLETED})()
        mock_repo = type("Repo", (), {"list_sessions": AsyncMock(return_value=[session1])})()
        data = json.loads(build_state_json(state_repo=mock_repo))
        assert data["status"] == "idle"

    def test_schedule_json_with_scheduler_returns_jobs(self) -> None:
        class FakeJob:
            def to_dict(self):
                return {"job_id": "j1", "name": "backup", "status": "active"}

        mock_sched = type("Sched", (), {"list_jobs": lambda self: [FakeJob()]})()
        data = json.loads(build_schedule_json(scheduler=mock_sched))
        assert data["total"] == 1
        assert data["jobs"][0]["job_id"] == "j1"

    def test_schedule_json_error_in_scheduler_returns_empty_jobs(self) -> None:
        mock_sched = type(
            "Sched", (), {"list_jobs": lambda self: (_ for _ in ()).throw(RuntimeError("db error"))}
        )()
        data = json.loads(build_schedule_json(scheduler=mock_sched))
        assert data["jobs"] == []
        assert data["error"] == "internal_error"

    def test_state_json_error_is_sanitized(self) -> None:
        mock_repo = type(
            "Repo", (), {"list_sessions": AsyncMock(side_effect=RuntimeError("DB password leaked"))}
        )()
        data = json.loads(build_state_json(state_repo=mock_repo))
        assert data["status"] == "error"
        assert data["error"] == "internal_error"

    def test_roadmap_json_error_is_sanitized(self) -> None:
        data = json.loads(build_roadmap_json(product_db_path="Z:\\definitely_missing\\x.db"))
        assert data["requirements"] == []
        assert data["error"] == "internal_error"

    @pytest.mark.asyncio
    async def test_server_passes_state_manager_to_resource(self) -> None:
        from weebot.domain.models.session import SessionStatus

        session1 = type("S", (), {"session_id": "live", "status": SessionStatus.RUNNING})()
        mock_repo = type("Repo", (), {"list_sessions": AsyncMock(return_value=[session1])})()
        server = WeebotMCPServer(state_manager=mock_repo)
        contents = await server.mcp.read_resource("weebot://state")
        data = json.loads(contents[0].content)
        assert data["total_sessions"] == 1
        assert data["status"] == "active"
