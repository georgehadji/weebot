"""Unit tests for ReasonerTool and its integration with the registry."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.tools.tool_registry import RoleBasedToolRegistry
from weebot.tools.reasoner import ReasonerTool
from weebot.tools.base import ToolResult


class TestReasonerTool:
    """Tests for ReasonerTool and registry registration."""

    def test_reasoner_tool_registry_registration(self):
        """Verify the reasoner tool is discoverable in the registry and assigned to correct roles."""
        registry = RoleBasedToolRegistry()

        # Verify it exists in classes
        class_map = registry.build_tool_class_map()
        assert "reasoner" in class_map
        assert class_map["reasoner"] == ReasonerTool

        # Verify authorized for researcher and analyst roles
        researcher_tools = registry.get_tools_for_role("researcher")
        assert "reasoner" in researcher_tools

        analyst_tools = registry.get_tools_for_role("analyst")
        assert "reasoner" in analyst_tools

        admin_tools = registry.get_tools_for_role("admin")
        assert "reasoner" in admin_tools

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    @patch("httpx.AsyncClient.post")
    async def test_reasoner_tool_successful_execution(self, mock_post, mock_get):
        """Verify successful reasoner tool execution with contract discovery and response parsing."""
        # Mock Discovery
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get.return_value = mock_get_resp

        # Mock Reasoner POST Response
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "synthesis": "We should use a distributed model here.",
            "citations": ["https://example.com/source"],
            "models_used": ["openai/gpt-4o"],
            "errors": [],
        }
        mock_post.return_value = mock_post_resp

        tool = ReasonerTool()
        result = await tool.execute(problem="What architecture should we use?")

        assert isinstance(result, ToolResult)
        assert result.data["synthesis"] == "We should use a distributed model here."
        assert "https://example.com/source" in result.data["citations"]
        assert "openai/gpt-4o" in result.data["models_used"]
        assert "Reasoner final answer" in result.output

        # Verify discovery call was made
        mock_get.assert_called()
        # Verify sync POST call was made
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    @patch("httpx.AsyncClient.post")
    async def test_reasoner_tool_retry_on_missing_synthesis(self, mock_post, mock_get):
        """Verify that tool automatically retries with web_search=True if synthesis is missing."""
        # Mock Discovery
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get.return_value = mock_get_resp

        # First POST response missing synthesis, second POST has it
        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.json.return_value = {"synthesis": None, "errors": ["Failed to find local info"]}

        second_resp = MagicMock()
        second_resp.status_code = 200
        second_resp.json.return_value = {
            "synthesis": "Retried and found facts.",
            "citations": ["web-source"],
            "models_used": ["google/gemini-pro"],
        }

        mock_post.side_effect = [first_resp, second_resp]

        tool = ReasonerTool()
        result = await tool.execute(problem="Solve the mystery", web_search=False)

        assert isinstance(result, ToolResult)
        assert result.data["synthesis"] == "Retried and found facts."
        assert "web-source" in result.data["citations"]

        # Verify it was called twice (first time, then retry with web_search=True)
        assert mock_post.call_count == 2

        # Verify that web_search was updated to True on the second call
        args, kwargs = mock_post.call_args_list[1]
        assert kwargs["json"]["web_search"] is True

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    @patch("httpx.AsyncClient.post")
    @patch("asyncio.create_subprocess_exec")
    async def test_reasoner_tool_cli_fallback_success(self, mock_subprocess, mock_post, mock_get):
        """Verify that tool automatically falls back to headless CLI execution if API calls fail."""
        import httpx

        # Discovery fails with HTTP connection error
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        # Post fails with Connection refused
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        # Mock asyncio.create_subprocess_exec
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"Headless CLI execution logs\n", b"")
        mock_subprocess.return_value = mock_process

        with (
            patch("builtins.open", MagicMock()),
            patch("pathlib.Path.exists") as mock_exists,
            patch("json.load") as mock_load,
        ):

            mock_exists.return_value = True
            mock_load.return_value = {
                "synthesis": "CLI synthesized result.",
                "citations": ["cli-source"],
                "models_used": ["cli-model"],
            }

            tool = ReasonerTool()
            result = await tool.execute(problem="Check CLI fallback")

            assert isinstance(result, ToolResult)
            assert result.data["synthesis"] == "CLI synthesized result."
            assert "cli-source" in result.data["citations"]
            assert "cli-model" in result.data["models_used"]
            assert "Reasoner final answer" in result.output

            # Verify subprocess was spawned
            mock_subprocess.assert_called_once()
