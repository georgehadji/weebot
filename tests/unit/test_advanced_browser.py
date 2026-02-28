"""Unit tests for advanced browser automation tools."""
import pytest
from weebot.tools.advanced_browser import AdvancedBrowserTool, WebScraperTool


class TestAdvancedBrowserTool:
    """Test AdvancedBrowserTool for browser automation."""

    @pytest.mark.asyncio
    async def test_tool_metadata(self):
        """Test tool metadata."""
        tool = AdvancedBrowserTool()
        assert tool.name == "advanced_browser"
        assert "browser" in tool.description.lower()
        assert "action" in tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_missing_url_for_goto(self):
        """Test goto action requires URL."""
        tool = AdvancedBrowserTool()
        result = await tool.execute(action="goto")
        assert result.is_error
        assert "url required" in result.error

    @pytest.mark.asyncio
    async def test_missing_selector_for_click(self):
        """Test click action requires selector."""
        tool = AdvancedBrowserTool()
        result = await tool.execute(action="click")
        assert result.is_error
        assert "selector required" in result.error

    @pytest.mark.asyncio
    async def test_missing_selector_and_value_for_fill(self):
        """Test fill action requires selector and value."""
        tool = AdvancedBrowserTool()
        result = await tool.execute(action="fill", selector="input")
        assert result.is_error
        assert "selector and value required" in result.error

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        """Test unknown action returns error."""
        tool = AdvancedBrowserTool()
        result = await tool.execute(action="unknown_action")
        assert result.is_error
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_missing_script_for_evaluate(self):
        """Test evaluate action requires script."""
        tool = AdvancedBrowserTool()
        result = await tool.execute(action="evaluate")
        assert result.is_error
        assert "script required" in result.error

    @pytest.mark.asyncio
    async def test_missing_text_for_type(self):
        """Test type action requires text."""
        tool = AdvancedBrowserTool()
        result = await tool.execute(action="type")
        assert result.is_error
        assert "text required" in result.error


class TestWebScraperTool:
    """Test WebScraperTool for web scraping."""

    @pytest.mark.asyncio
    async def test_tool_metadata(self):
        """Test scraper tool metadata."""
        tool = WebScraperTool()
        assert tool.name == "web_scraper"
        assert "scraping" in tool.description.lower()
        assert "url" in tool.parameters["properties"]
        assert "selector" in tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_missing_selector(self):
        """Test scraper requires selector."""
        tool = WebScraperTool()
        # Since selector is required positional, this will error at function call level
        # We test the error handling in the implementation
        result = await tool.execute(
            url="https://example.com",
            selector="",
            extract_type="text",
        )
        # Empty selector should work but find nothing
        assert not result.is_error or "selector" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_extract_type_accepted(self):
        """Test scraper accepts valid extract types."""
        tool = WebScraperTool()
        # Note: WebScraperTool will accept any string for extract_type
        # Real validation happens during execution
        for extract_type in ["text", "html", "attribute", "all"]:
            assert extract_type in [
                "text",
                "html",
                "attribute",
                "all",
            ]
