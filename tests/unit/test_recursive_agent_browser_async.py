"""Tests for RecursiveWeebotAgent browser tool execution."""
import pytest
from unittest.mock import AsyncMock, patch

from weebot.core.agent import RecursiveWeebotAgent


@pytest.mark.asyncio
async def test_browser_tool_uses_async_path():
    with patch("weebot.core.agent.ChatOpenAI"), patch("weebot.core.safety.ChatOpenAI"):
        agent = RecursiveWeebotAgent()

    routing = {
        "primary_tool": "browser",
        "confidence": 1.0,
        "reasoning": "test",
        "suggested_sequence": ["browser", "powershell"],
    }

    with patch.object(agent.heuristic_router, "analyze_task", return_value=routing):
        with patch.object(agent.browser_tool, "_arun", new=AsyncMock(return_value="ok")) as arun_mock:
            with patch.object(agent.browser_tool, "_run", side_effect=AssertionError("sync run should not be called")):
                result = await agent.execute_task("visit example.com")

    assert result["status"] == "success"
    assert result["tool_used"] == "browser"
    arun_mock.assert_awaited()
