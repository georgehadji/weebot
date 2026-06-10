import os
import pytest
import httpx
from weebot.tools.vane_search import VaneSearchTool
from weebot.config.settings import WeebotSettings

# Mark the entire module to be skipped if VANE_BASE_URL is not set
pytestmark = pytest.mark.skipif(
    not os.getenv("VANE_BASE_URL"),
    reason="VANE_BASE_URL not set, skipping Vane integration tests."
)

@pytest.fixture(scope="module")
def vane_base_url():
    return os.getenv("VANE_BASE_URL")

@pytest.mark.asyncio
async def test_vane_integration_basic_search(vane_base_url):
    settings = WeebotSettings() # Load settings to get vane_base_url and http_timeout_default
    # Ensure we are not using the mocked settings from unit tests
    settings.vane_base_url = vane_base_url

    tool = VaneSearchTool()
    tool.settings = settings # Inject settings

    query = "What is the capital of France?"
    result = await tool.execute(query=query)

    assert result.success is True
    assert "Paris" in result.output
    assert "sources" in result.metadata
    assert len(result.metadata["sources"]) > 0
    assert "vane_response_raw" in result.metadata

@pytest.mark.asyncio
async def test_vane_integration_academic_search(vane_base_url):
    settings = WeebotSettings()
    settings.vane_base_url = vane_base_url

    tool = VaneSearchTool()
    tool.settings = settings # Inject settings

    query = "Recent advancements in quantum computing academic papers"
    result = await tool.execute(query=query, focus_mode="academicSearch", optimization="quality")

    assert result.success is True
    assert len(result.output) > 50 # Expect a substantial answer
    assert "sources" in result.metadata
    assert (
        any("arxiv.org" in s.get("url", "") for s in result.metadata["sources"])
        or any("ieee.org" in s.get("url", "") for s in result.metadata["sources"])
    )


@pytest.mark.asyncio
async def test_vane_integration_invalid_url_handling(monkeypatch):
    # This test explicitly mocks the VANE_BASE_URL to be invalid
    monkeypatch.setenv("VANE_BASE_URL", "http://not-a-real-url:12345")
    settings = WeebotSettings()

    tool = VaneSearchTool()
    # Since the fixture sets the settings, we need to ensure the tool uses the mocked invalid URL.
    # Reloading settings to pick up monkeypatched env var.
    tool.settings = settings

    query = "Test invalid URL"
    result = await tool.execute(query=query)

    assert result.success is False
    assert "Vane API request failed" in result.error or "Invalid Vane base URL" in result.error
