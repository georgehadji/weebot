"""web_scraper obtains its browser through BrowserPort, not through Playwright directly.

The composition root supplies ``browser_factory`` (a fresh adapter per call). The scraper
starts it, reads the page through the port, and always closes it. The CDP policy (connect,
launch or refuse) then lives in one place, the adapter's launcher, and a refusal reaches the
agent as a plain tool error.
"""

from __future__ import annotations

import pytest

from weebot.application.ports.browser_port import BrowserConfig, NavigationResult
from weebot.tools.advanced_browser import WebScraperTool

HTML = (
    "<html><head><title>t</title></head><body>"
    "<h1>Hello</h1><a class='x' href='/a'>one</a><a class='x' href='/b'>two</a>"
    "</body></html>"
)


class FakeBrowser:
    """Records what the scraper asks of a BrowserPort."""

    def __init__(self, *, nav: NavigationResult | None = None, html=HTML, waits=True):
        self.nav = nav or NavigationResult(
            success=True, url="https://example.com", status_code=200, error=None, load_time_ms=1.0
        )
        self.html = html
        self.waits = waits
        self.config: BrowserConfig | None = None
        self.navigated: tuple | None = None
        self.waited: tuple | None = None
        self.closed = 0

    async def start(self, config=None):
        self.config = config

    async def navigate(self, url, wait_until="networkidle", timeout=None):
        self.navigated = (url, wait_until, timeout)
        return self.nav

    async def wait_for_selector(self, selector, timeout=30.0, state="visible"):
        self.waited = (selector, timeout)
        return self.waits

    async def evaluate(self, script, selector=None):
        assert "outerHTML" in script
        return self.html

    async def close(self):
        self.closed += 1


def _tool(browser: FakeBrowser) -> WebScraperTool:
    return WebScraperTool(browser_factory=lambda: browser)


@pytest.mark.asyncio
async def test_scrapes_through_the_injected_browser():
    fake = FakeBrowser()
    result = await _tool(fake).execute(url="https://example.com", selector="a.x")
    assert not result.error
    assert "one" in result.output and "two" in result.output
    assert fake.config is not None and fake.config.headless is True
    assert fake.navigated == ("https://example.com", "networkidle", 30.0)
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_timeout_is_passed_in_seconds_to_navigation_and_wait():
    fake = FakeBrowser()
    await _tool(fake).execute(
        url="https://example.com", selector="h1", wait_for="h1", timeout=5000
    )
    assert fake.navigated[2] == 5.0
    assert fake.waited == ("h1", 5.0)


@pytest.mark.asyncio
async def test_an_http_error_page_is_still_scraped():
    """goto never raised on a 404; the page body is still data."""
    nav = NavigationResult(
        success=False, url="https://example.com", status_code=404, error="HTTP 404",
        load_time_ms=1.0,
    )
    fake = FakeBrowser(nav=nav)
    result = await _tool(fake).execute(url="https://example.com", selector="h1")
    assert not result.error and "Hello" in result.output


@pytest.mark.asyncio
async def test_a_failed_navigation_is_a_tool_error_and_the_browser_closes():
    nav = NavigationResult(
        success=False, url="", status_code=0, error="net::ERR_NAME_NOT_RESOLVED", load_time_ms=1.0
    )
    fake = FakeBrowser(nav=nav)
    result = await _tool(fake).execute(url="https://nope.invalid", selector="h1")
    assert result.error and "ERR_NAME_NOT_RESOLVED" in result.error
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_a_wait_that_times_out_is_a_tool_error():
    fake = FakeBrowser(waits=False)
    result = await _tool(fake).execute(url="https://example.com", selector="h1", wait_for="#late")
    assert result.error and "#late" in result.error
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_markdown_closes_the_browser_once():
    fake = FakeBrowser()
    result = await _tool(fake).execute(
        url="https://example.com", selector="body", extract_type="markdown"
    )
    assert not result.error and result.data["markdown"]
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_the_browser_closes_when_extraction_raises(monkeypatch):
    fake = FakeBrowser()

    async def boom(*_a, **_k):
        raise RuntimeError("page crashed")

    monkeypatch.setattr(fake, "evaluate", boom)
    result = await _tool(fake).execute(url="https://example.com", selector="h1")
    assert result.error and "page crashed" in result.error
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_an_unreadable_page_is_a_tool_error():
    fake = FakeBrowser(html={"error": "context destroyed"})
    result = await _tool(fake).execute(url="https://example.com", selector="h1")
    assert result.error and "context destroyed" in result.error
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_each_scrape_asks_the_factory_for_its_own_browser():
    made = []

    def factory():
        made.append(FakeBrowser())
        return made[-1]

    tool = WebScraperTool(browser_factory=factory)
    await tool.execute(url="https://example.com", selector="h1")
    await tool.execute(url="https://example.com", selector="h1")
    assert len(made) == 2 and all(b.closed == 1 for b in made)


def test_the_registry_hands_the_scraper_the_factory():
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    def factory():
        return FakeBrowser()

    registry = RoleBasedToolRegistry(wiring=lambda: {"browser_factory": factory})
    tools = registry.create_tool_collection_from_names(["web_scraper"])
    scraper = next(t for t in tools if t.name == "web_scraper")
    assert scraper.browser_factory is factory
