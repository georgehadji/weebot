"""Unit tests for BrowserInspectorTool.

Playwright is mocked — no real browser is launched. Tests verify:
- ToolResult.data structure for each action
- Error handling (no browser session, missing selector, bad action)
- Integration with advanced_browser module-level state
"""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.tools.browser_inspector import BrowserInspectorTool
from weebot.tools.base import ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_page(url: str = "https://example.com") -> MagicMock:
    """Return a MagicMock standing in for a Playwright Page."""
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value="Example Domain")
    page.evaluate = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    return page


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestBrowserInspectorMetadata:
    def test_tool_name(self):
        assert BrowserInspectorTool().name == "browser_inspector"

    def test_description_mentions_tokens(self):
        assert "design token" in BrowserInspectorTool().description.lower()

    def test_parameters_have_action_enum(self):
        params = BrowserInspectorTool().parameters
        actions = params["properties"]["action"]["enum"]
        assert "extract_design_tokens" in actions
        assert "inspect_element" in actions
        assert "enumerate_assets" in actions
        assert "get_structure" in actions
        assert "screenshot" in actions
        assert "navigate" in actions

    def test_action_is_required(self):
        params = BrowserInspectorTool().parameters
        assert "action" in params["required"]


# ---------------------------------------------------------------------------
# No browser session guard
# ---------------------------------------------------------------------------

class TestNoBrowserSession:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_page(self):
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", None):
            result = await tool.execute(action="extract_design_tokens")
        assert result.is_error
        assert "No browser session" in result.error

    @pytest.mark.asyncio
    async def test_screenshot_returns_error_when_no_page(self):
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", None):
            result = await tool.execute(action="screenshot")
        assert result.is_error


# ---------------------------------------------------------------------------
# extract_design_tokens
# ---------------------------------------------------------------------------

class TestExtractDesignTokens:
    @pytest.mark.asyncio
    async def test_returns_structured_data(self):
        page = _make_mock_page()
        page.evaluate.return_value = {
            "custom_properties": {"--color-primary": "#3b82f6", "--spacing-md": "1rem"},
            "computed_root": {"font-family": "Inter", "font-size": "16px"},
        }
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="extract_design_tokens")

        assert result.success
        assert result.data["custom_properties"]["--color-primary"] == "#3b82f6"
        assert result.data["computed_root"]["font-family"] == "Inter"
        assert "2 CSS custom properties" in result.output

    @pytest.mark.asyncio
    async def test_empty_tokens_still_succeeds(self):
        page = _make_mock_page()
        page.evaluate.return_value = {"custom_properties": {}, "computed_root": {}}
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="extract_design_tokens")

        assert result.success
        assert result.data["custom_properties"] == {}


# ---------------------------------------------------------------------------
# inspect_element
# ---------------------------------------------------------------------------

class TestInspectElement:
    @pytest.mark.asyncio
    async def test_requires_selector(self):
        page = _make_mock_page()
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="inspect_element")
        assert result.is_error
        assert "selector" in result.error.lower()

    @pytest.mark.asyncio
    async def test_element_not_found_returns_error(self):
        page = _make_mock_page()
        page.evaluate.return_value = None
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="inspect_element", selector="#missing")
        assert result.is_error
        assert "#missing" in result.error

    @pytest.mark.asyncio
    async def test_returns_computed_css(self):
        page = _make_mock_page()
        page.evaluate.return_value = {
            "tag": "section",
            "classes": ["hero"],
            "text_content": "Welcome",
            "bounding_box": {"x": 0, "y": 0, "width": 1440, "height": 600},
            "computed_css": {
                "fontFamily": "Inter",
                "fontSize": "48px",
                "color": "rgb(255,255,255)",
                "backgroundColor": "rgb(15,15,15)",
            },
        }
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="inspect_element", selector=".hero")

        assert result.success
        assert result.data["tag"] == "section"
        assert result.data["computed_css"]["fontFamily"] == "Inter"
        assert "1440x600" in result.output


# ---------------------------------------------------------------------------
# enumerate_assets
# ---------------------------------------------------------------------------

class TestEnumerateAssets:
    @pytest.mark.asyncio
    async def test_returns_asset_list(self):
        page = _make_mock_page()
        page.evaluate.return_value = [
            {"type": "img", "src": "https://example.com/hero.png", "alt": "Hero", "width": 800, "height": 400, "position": {"x": 0, "y": 0}},
            {"type": "inline-svg", "id": "logo", "viewBox": "0 0 24 24", "width": 24, "height": 24, "position": {"x": 10, "y": 10}},
        ]
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="enumerate_assets")

        assert result.success
        assert result.data["counts"]["img"] == 1
        assert result.data["counts"]["inline-svg"] == 1
        assert len(result.data["assets"]) == 2

    @pytest.mark.asyncio
    async def test_resolves_relative_urls(self):
        page = _make_mock_page(url="https://example.com/page")
        page.evaluate.return_value = [
            {"type": "img", "src": "/images/hero.png", "alt": "", "width": 100, "height": 100, "position": {"x": 0, "y": 0}},
        ]
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="enumerate_assets")

        assert result.data["assets"][0]["src"] == "https://example.com/images/hero.png"

    @pytest.mark.asyncio
    async def test_empty_assets_succeeds(self):
        page = _make_mock_page()
        page.evaluate.return_value = []
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="enumerate_assets")

        assert result.success
        assert result.data["assets"] == []


# ---------------------------------------------------------------------------
# get_structure
# ---------------------------------------------------------------------------

class TestGetStructure:
    @pytest.mark.asyncio
    async def test_returns_structure_and_title(self):
        page = _make_mock_page()
        page.evaluate.return_value = {
            "tag": "body",
            "id": None,
            "classes": [],
            "text_preview": "",
            "bounding_box": {"x": 0, "y": 0, "width": 1440, "height": 4000},
            "children": [
                {"tag": "header", "id": None, "classes": ["site-header"], "text_preview": "Logo", "bounding_box": {"x": 0, "y": 0, "width": 1440, "height": 80}, "children": []},
                {"tag": "main", "id": None, "classes": [], "text_preview": "", "bounding_box": {"x": 0, "y": 80, "width": 1440, "height": 3800}, "children": []},
            ],
        }
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="get_structure")

        assert result.success
        assert result.data["title"] == "Example Domain"
        assert result.data["structure"]["tag"] == "body"
        assert "3 structural nodes" in result.output


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------

class TestScreenshot:
    @pytest.mark.asyncio
    async def test_returns_base64_image(self):
        page = _make_mock_page()
        raw = b"\x89PNG\r\n" + b"\xff" * 50
        page.screenshot = AsyncMock(return_value=raw)
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            result = await tool.execute(action="screenshot")

        assert result.success
        assert result.base64_image is not None
        decoded = base64.b64decode(result.base64_image)
        assert decoded == raw
        assert result.data["format"] == "png"

    @pytest.mark.asyncio
    async def test_screenshot_calls_full_page(self):
        page = _make_mock_page()
        tool = BrowserInspectorTool()
        with patch("weebot.tools.advanced_browser._page", page):
            await tool.execute(action="screenshot")
        page.screenshot.assert_called_once_with(full_page=True)


# ---------------------------------------------------------------------------
# navigate action
# ---------------------------------------------------------------------------

class TestNavigateAction:
    @pytest.mark.asyncio
    async def test_navigate_requires_url(self):
        tool = BrowserInspectorTool()
        result = await tool.execute(action="navigate")
        assert result.is_error
        assert "url is required" in result.error

    @pytest.mark.asyncio
    async def test_navigate_delegates_to_advanced_browser(self):
        tool = BrowserInspectorTool()
        mock_result = ToolResult(output="Navigated to https://example.com", success=True)
        with patch(
            "weebot.tools.advanced_browser.AdvancedBrowserTool.execute",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await tool.execute(action="navigate", url="https://example.com")
        assert result.success
        assert result.data["url"] == "https://example.com"
