"""Unit tests for BerbTool and its integration with the registry."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.tools.tool_registry import RoleBasedToolRegistry
from weebot.tools.berb import BerbTool
from weebot.tools.base import ToolResult


class TestBerbTool:
    """Tests for BerbTool and registry registration."""

    def test_berb_tool_registry_registration(self):
        """Verify the berb tool is discoverable in the registry and assigned to correct roles."""
        registry = RoleBasedToolRegistry()

        # Verify it exists in classes
        class_map = registry.build_tool_class_map()
        assert "berb" in class_map
        assert class_map["berb"] == BerbTool

        # Verify authorized for researcher and analyst roles
        researcher_tools = registry.get_tools_for_role("researcher")
        assert "berb" in researcher_tools

        analyst_tools = registry.get_tools_for_role("analyst")
        assert "berb" in analyst_tools

        admin_tools = registry.get_tools_for_role("admin")
        assert "berb" in admin_tools

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_berb_tool_successful_cli_execution(self, mock_subprocess):
        """Verify successful default berb tool execution via headless CLI subprocess."""
        # Mock asyncio.create_subprocess_exec
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"Berb 23-stage run finished logs\n", b"")
        mock_subprocess.return_value = mock_process

        tool = BerbTool()
        result = await tool.execute(topic="LLM Hallucinations")

        assert isinstance(result, ToolResult)
        assert result.data["topic"] == "LLM Hallucinations"
        assert "finished logs" in result.data["summary"]
        assert "Berb Academic Research Output" in result.output

        # Verify subprocess was spawned (Method 1: CLI default)
        mock_subprocess.assert_called_once()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    @patch("asyncio.create_subprocess_exec")
    async def test_berb_tool_fallback_to_api_success(self, mock_subprocess, mock_post):
        """Verify that berb tool automatically falls back to API (Method 2) if CLI execution fails."""

        # Mock CLI execution failure
        mock_subprocess.side_effect = RuntimeError("Subprocess execution failed")

        # Mock API response success
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "status": "success",
            "message": "API academic research run completed successfully.",
            "summary": "Full academic report details from API.",
            "artifacts_dir": "E:\\Documents\\Vibe-Coding\\Berb\\artifacts",
        }
        mock_post.return_value = mock_post_resp

        tool = BerbTool()
        result = await tool.execute(topic="Distributed consensus architectures")

        assert isinstance(result, ToolResult)
        assert result.data["topic"] == "Distributed consensus architectures"
        assert result.data["summary"] == "Full academic report details from API."
        assert "artifacts" in result.data["artifacts_dir"]
        assert "Berb Academic Research Output" in result.output

        # Verify CLI was attempted
        mock_subprocess.assert_called_once()
        # Verify API was called as fallback
        mock_post.assert_called_once()
