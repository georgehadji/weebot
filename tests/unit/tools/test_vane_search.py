import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from weebot.tools.vane_search import VaneSearchTool, ToolResult


@pytest.fixture
def mock_vane_settings(monkeypatch):
    # VaneSearchTool reads the base URL from the VANE_BASE_URL env var.
    monkeypatch.setenv("VANE_BASE_URL", "http://mock-vane:3000")
    yield


def _mock_client(MockAsyncClient):
    """Return the (awaited) client instance from a patched httpx.AsyncClient.

    MagicMock auto-provides async-context-manager dunders, so ``async with
    httpx.AsyncClient() as client`` yields ``__aenter__.return_value``.
    """
    return MockAsyncClient.return_value.__aenter__.return_value


def _mock_response(*, status_code=200, json_data=None, raise_exc=None):
    """Build a SYNC response mock (httpx Response.json/raise_for_status are sync)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if raise_exc is not None:
        resp.raise_for_status.side_effect = raise_exc
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.mark.asyncio
async def test_vane_search_success(mock_vane_settings):
    tool = VaneSearchTool()
    mock_response_data = {
        "message": "This is a synthesized answer from Vane.",
        "sources": [
            {
                "metadata": {"title": "Source 1", "url": "http://example.com/1"},
                "content": "Content from source 1."
            },
            {
                "metadata": {"title": "Source 2", "url": "http://example.com/2"},
                "content": "Content from source 2."
            },
        ],
    }

    with patch('httpx.AsyncClient') as MockAsyncClient:
        client = _mock_client(MockAsyncClient)
        client.post = AsyncMock(return_value=_mock_response(json_data=mock_response_data))

        result = await tool.execute(query="What is agentic coding?")

        assert isinstance(result, ToolResult)
        assert result.output == "This is a synthesized answer from Vane."
        assert "sources" in result.metadata
        assert len(result.metadata["sources"]) == 2
        assert result.metadata["sources"][0]["title"] == "Source 1"
        assert result.metadata["sources"][1]["url"] == "http://example.com/2"
        assert "vane_response_raw" in result.metadata
        assert result.metadata["vane_response_raw"] == mock_response_data
        client.post.assert_called_once_with(
            "http://mock-vane:3000/api/search",
            json={
                "query": "What is agentic coding?",
                "focusMode": "webSearch",
                "optimizationMode": "balanced",
                "stream": False,
            },
        )


@pytest.mark.asyncio
async def test_vane_search_http_error(mock_vane_settings):
    tool = VaneSearchTool()
    with patch('httpx.AsyncClient') as MockAsyncClient:
        client = _mock_client(MockAsyncClient)
        resp = _mock_response(
            status_code=500,
            raise_exc=httpx.HTTPStatusError(
                "Internal Server Error",
                request=httpx.Request("POST", "http://mock-vane:3000/api/search"),
                response=MagicMock(status_code=500, text="Internal Server Error"),
            ),
        )
        client.post = AsyncMock(return_value=resp)

        result = await tool.execute(query="Invalid query")

        assert isinstance(result, ToolResult)
        assert result.output == ""
        assert "Vane API returned an error 500" in result.error


@pytest.mark.asyncio
async def test_vane_search_request_error(mock_vane_settings):
    tool = VaneSearchTool()
    with patch('httpx.AsyncClient') as MockAsyncClient:
        client = _mock_client(MockAsyncClient)
        client.post = AsyncMock(side_effect=httpx.RequestError(
            "Network error", request=httpx.Request("POST", "http://mock-vane:3000/api/search")
        ))

        result = await tool.execute(query="Network issue")

        assert isinstance(result, ToolResult)
        assert result.output == ""
        assert "Vane API request failed" in result.error


@pytest.mark.asyncio
async def test_vane_search_no_message_or_sources(mock_vane_settings):
    tool = VaneSearchTool()
    mock_response_data = {"some_other_field": "value"}

    with patch('httpx.AsyncClient') as MockAsyncClient:
        client = _mock_client(MockAsyncClient)
        client.post = AsyncMock(return_value=_mock_response(json_data=mock_response_data))

        result = await tool.execute(query="Empty response")

        assert isinstance(result, ToolResult)
        assert result.output == "No message provided by Vane."
        assert "sources" in result.metadata
        assert len(result.metadata["sources"]) == 0


@pytest.mark.asyncio
async def test_vane_search_focus_mode_and_optimization(mock_vane_settings):
    tool = VaneSearchTool()
    mock_response_data = {"message": "Academic result", "sources": []}

    with patch('httpx.AsyncClient') as MockAsyncClient:
        client = _mock_client(MockAsyncClient)
        client.post = AsyncMock(return_value=_mock_response(json_data=mock_response_data))

        result = await tool.execute(
            query="Quantum physics breakthroughs",
            focus_mode="academicSearch",
            optimization="quality"
        )

        assert isinstance(result, ToolResult)
        client.post.assert_called_once_with(
            "http://mock-vane:3000/api/search",
            json={
                "query": "Quantum physics breakthroughs",
                "focusMode": "academicSearch",
                "optimizationMode": "quality",
                "stream": False,
            },
        )
