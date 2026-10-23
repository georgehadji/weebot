"""Unit tests for WebSearchTool."""

import pytest
from unittest.mock import AsyncMock, patch

from weebot.tools.web_search import WebSearchTool


@pytest.mark.asyncio
async def test_execute_uses_duckduckgo_primary():
    """execute returns results from DuckDuckGo when available."""
    tool = WebSearchTool()
    mock_results = [{"title": "Test", "url": "http://example.com", "snippet": "snippet"}]
    with patch.object(tool, "_search_duckduckgo", AsyncMock(return_value=mock_results)):
        result = await tool.execute(query="test query")
    assert not result.is_error
    assert "Test" in result.output


@pytest.mark.asyncio
async def test_execute_falls_back_to_bing():
    """When DuckDuckGo fails, execute tries Bing."""
    tool = WebSearchTool()
    mock_results = [{"title": "Bing Result", "url": "http://bing.com", "snippet": ""}]
    with (
        patch.object(tool, "_search_duckduckgo", AsyncMock(side_effect=ValueError("No results"))),
        patch.object(tool, "_search_bing", AsyncMock(return_value=mock_results)),
    ):
        result = await tool.execute(query="test")
    assert not result.is_error
    assert "Bing Result" in result.output


@pytest.mark.asyncio
async def test_execute_returns_error_when_all_fail():
    """Returns ToolResult with error when both engines fail."""
    tool = WebSearchTool()
    with (
        patch.object(tool, "_search_duckduckgo", AsyncMock(side_effect=Exception("DDG down"))),
        patch.object(tool, "_search_bing", AsyncMock(side_effect=Exception("Bing down"))),
    ):
        result = await tool.execute(query="test")
    assert result.is_error
    assert "DDG down" in result.error


@pytest.mark.asyncio
async def test_num_results_clamped_to_max():
    """num_results > 10 is clamped to 10."""
    tool = WebSearchTool()
    captured: dict = {}

    async def capture(query, num_results):
        captured["num_results"] = num_results
        return [{"title": "x", "url": "y", "snippet": ""}]

    with patch.object(tool, "_search_duckduckgo", capture):
        await tool.execute(query="q", num_results=100)
    # execute() clamps to 10, then over-fetches 2x candidates for reranking.
    assert captured["num_results"] == 20


@pytest.mark.asyncio
async def test_num_results_clamped_to_min():
    """num_results < 1 is clamped to 1."""
    tool = WebSearchTool()
    captured: dict = {}

    async def capture(query, num_results):
        captured["num_results"] = num_results
        return [{"title": "x", "url": "y", "snippet": ""}]

    with patch.object(tool, "_search_duckduckgo", capture):
        await tool.execute(query="q", num_results=0)
    # execute() clamps to 1, then over-fetches 2x candidates for reranking.
    assert captured["num_results"] == 2


def test_format_produces_numbered_output():
    """_format produces readable numbered list with URL and snippet."""
    tool = WebSearchTool()
    results = [
        {"title": "Alpha", "url": "http://alpha.com", "snippet": "About Alpha"},
        {"title": "Beta", "url": "http://beta.com", "snippet": ""},
    ]
    output = tool._format(results)
    assert "1. Alpha" in output
    assert "http://alpha.com" in output
    assert "About Alpha" in output
    assert "2. Beta" in output


def test_to_param_shape():
    """Tool param schema has correct OpenAI function spec structure."""
    tool = WebSearchTool()
    param = tool.to_param()
    assert param["type"] == "function"
    assert param["function"]["name"] == "web_search"
    assert "query" in param["function"]["parameters"]["required"]


@pytest.mark.asyncio
async def test_enough_results_from_the_first_engine_skip_the_others():
    """All three engines ran in series on every search, whatever the first
    returned: a 20 s Perplexity budget, then DuckDuckGo, then Bing."""
    tool = WebSearchTool()
    enough = [{"title": f"t{i}", "url": f"https://x/{i}", "snippet": "s"} for i in range(5)]
    ddg = AsyncMock(return_value=[])
    bing = AsyncMock(return_value=[])
    with (
        patch.object(tool, "_search_perplexity", AsyncMock(return_value=enough)),
        patch.object(tool, "_search_duckduckgo", ddg),
        patch.object(tool, "_search_bing", bing),
    ):
        result = await tool.execute(query="q", num_results=5)
    assert result.error is None
    ddg.assert_not_called()
    bing.assert_not_called()


@pytest.mark.asyncio
async def test_too_few_results_still_try_the_next_engine():
    tool = WebSearchTool()
    one = [{"title": "t", "url": "https://x/1", "snippet": "s"}]
    more = [{"title": f"d{i}", "url": f"https://d/{i}", "snippet": "s"} for i in range(5)]
    bing = AsyncMock(return_value=[])
    with (
        patch.object(tool, "_search_perplexity", AsyncMock(return_value=one)),
        patch.object(tool, "_search_duckduckgo", AsyncMock(return_value=more)),
        patch.object(tool, "_search_bing", bing),
    ):
        result = await tool.execute(query="q", num_results=5)
    assert "https://d/0" in result.output
    bing.assert_not_called()
