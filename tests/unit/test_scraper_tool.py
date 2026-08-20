"""Unit tests for ScraperTool and its integration with the registry."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.tools.tool_registry import RoleBasedToolRegistry
from weebot.tools.scraper import ScraperTool
from weebot.tools.base import ToolResult


class TestScraperTool:
    """Tests for ScraperTool and registry registration."""

    def test_scraper_tool_registry_registration(self):
        """Verify the spacescraper tool is discoverable in the registry and assigned to correct roles."""
        registry = RoleBasedToolRegistry()

        # Verify it exists in classes
        class_map = registry.build_tool_class_map()
        assert "spacescraper" in class_map
        assert class_map["spacescraper"] == ScraperTool

        # Verify authorized for researcher, analyst, and admin roles
        researcher_tools = registry.get_tools_for_role("researcher")
        assert "spacescraper" in researcher_tools

        analyst_tools = registry.get_tools_for_role("analyst")
        assert "spacescraper" in analyst_tools

        admin_tools = registry.get_tools_for_role("admin")
        assert "spacescraper" in admin_tools

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_scraper_tool_successful_cli_execution(self, mock_subprocess):
        """Verify successful default spacescraper tool execution via headless CLI subprocess (Method 1)."""
        # Mock asyncio.create_subprocess_exec
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"Job Authorized & Queued: man_ss_f1e2a3\n", b"")
        mock_subprocess.return_value = mock_process

        tool = ScraperTool()
        result = await tool.execute(url="https://ted.europa.eu", site="esa_emits")

        assert isinstance(result, ToolResult)
        assert result.data["method"] == "cli"
        assert result.data["url"] == "https://ted.europa.eu"
        assert "man_ss_f1e2a3" in result.data["cli_output"]
        assert "dispatched via local CLI" in result.output

        # Verify subprocess was spawned (Method 1: CLI default)
        mock_subprocess.assert_called_once()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    @patch("asyncio.create_subprocess_exec")
    async def test_scraper_tool_fallback_to_api_success(self, mock_subprocess, mock_post):
        """Verify that spacescraper tool automatically falls back to API (Method 2) if CLI execution fails."""

        # Mock CLI execution failure
        mock_subprocess.side_effect = RuntimeError("Subprocess execution failed")

        # Mock API response success
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "status": "enqueued",
            "job_id": "api_ss_998877",
            "url": "https://nspa.nato.int",
        }
        mock_post.return_value = mock_post_resp

        tool = ScraperTool()
        result = await tool.execute(url="https://nspa.nato.int", site="nato_nspa")

        assert isinstance(result, ToolResult)
        assert result.data["method"] == "api"
        assert result.data["api_response"]["job_id"] == "api_ss_998877"
        assert "dispatched via REST API" in result.output

        # Verify CLI was attempted
        mock_subprocess.assert_called_once()
        # Verify API was called as fallback
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    @patch("asyncio.create_subprocess_exec")
    async def test_scraper_tool_fallback_to_docker_success(self, mock_subprocess, mock_post):
        """Verify fallback to Docker-Compose cluster up and API retry (Method 3) if both CLI and first API call fail."""
        import httpx

        # 1. First call to CLI subprocess fails with Exception
        # 2. Second call (Docker-Compose up subprocess) succeeds with 0 exit code
        mock_cli_proc = AsyncMock()
        mock_cli_proc.returncode = 1
        mock_cli_proc.communicate.return_value = (b"", b"CLI submission error")

        mock_docker_proc = AsyncMock()
        mock_docker_proc.returncode = 0
        mock_docker_proc.communicate.return_value = (b"Creating spacescraper-redis ... done\n", b"")

        # Configure side effect for subprocess calls:
        # First call is CLI subprocess (RuntimeError side effect or mock_cli_proc)
        # Second call is docker-compose subprocess (returns mock_docker_proc)
        mock_subprocess.side_effect = [
            RuntimeError("Subprocess execution failed"),
            mock_docker_proc,
        ]

        # Configure side effect for HTTP calls:
        # First POST call fails (Connection refused/Timeout)
        # Second POST call (after Docker up) succeeds!
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"status": "enqueued", "job_id": "docker_ss_554433"}
        mock_post.side_effect = [httpx.ConnectError("Connection refused"), mock_post_resp]

        tool = ScraperTool()
        result = await tool.execute(url="https://sam.gov", site="sam_gov")

        assert isinstance(result, ToolResult)
        assert result.data["method"] == "docker_compose"
        assert result.data["api_response"]["job_id"] == "docker_ss_554433"
        assert "launching Docker cluster" in result.output

        # Verify CLI and Docker-Compose up were both run
        assert mock_subprocess.call_count == 2
        # Verify initial API post failed and retry API post succeeded
        assert mock_post.call_count == 2
