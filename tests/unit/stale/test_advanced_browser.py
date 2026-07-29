"""Tests for AdvancedBrowserTool wait_type mapping and adapter integration."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.tools.advanced_browser import (
    AdvancedBrowserTool,
    _WAIT_TYPE_MAP,
)


class TestWaitTypeMapping:
    """Tests for wait_type → Playwright wait_until mapping."""

    def test_map_contains_all_expected_keys(self) -> None:
        assert "navigation" in _WAIT_TYPE_MAP
        assert "function" in _WAIT_TYPE_MAP
        assert "selector" in _WAIT_TYPE_MAP

    def test_navigation_maps_to_domcontentloaded(self) -> None:
        assert _WAIT_TYPE_MAP["navigation"] == "domcontentloaded"

    def test_function_maps_to_load(self) -> None:
        assert _WAIT_TYPE_MAP["function"] == "load"

    def test_selector_defaults_to_domcontentloaded(self) -> None:
        # selector waits for the element AFTER navigation
        assert _WAIT_TYPE_MAP["selector"] == "domcontentloaded"

    def test_unknown_wait_type_falls_back(self) -> None:
        assert _WAIT_TYPE_MAP.get("nonexistent", "domcontentloaded") == "domcontentloaded"


class TestAdvancedBrowserTool:
    """Tests for AdvancedBrowserTool with adapter injection."""

    def test_tool_accepts_browser_field(self) -> None:
        """Verify the tool accepts a browser adapter via constructor."""
        mock_adapter = MagicMock()
        tool = AdvancedBrowserTool(browser=mock_adapter)
        assert tool.browser is mock_adapter

    def test_tool_browser_defaults_to_none(self) -> None:
        """Verify browser field defaults to None (lazy init)."""
        tool = AdvancedBrowserTool()
        assert tool.browser is None

    def test_page_returns_none_without_adapter(self) -> None:
        """Verify _page() returns None when browser is not set."""
        tool = AdvancedBrowserTool()
        assert tool._page() is None

    def test_page_delegates_to_adapter(self) -> None:
        """Verify _page() delegates to adapter.page."""
        mock_adapter = MagicMock()
        mock_adapter.page = "mock_page"
        tool = AdvancedBrowserTool(browser=mock_adapter)
        assert tool._page() == "mock_page"


class TestBrowserInspectorTool:
    """Tests for BrowserInspectorTool with adapter injection."""

    def test_tool_accepts_browser_field(self) -> None:
        """Verify the tool accepts a browser adapter."""
        from weebot.tools.browser_inspector import BrowserInspectorTool
        mock_adapter = MagicMock()
        tool = BrowserInspectorTool(browser=mock_adapter)
        assert tool.browser is mock_adapter


class TestParameterSchema:
    """Validate the tool parameter schema is compatible with OpenAI tool calling."""

    def test_schema_has_required_action(self) -> None:
        tool = AdvancedBrowserTool()
        assert "action" in tool.parameters["required"]
        assert len(tool.parameters["required"]) == 1

    def test_wait_type_enum_values(self) -> None:
        tool = AdvancedBrowserTool()
        wait_type_prop = tool.parameters["properties"]["wait_type"]
        assert wait_type_prop["enum"] == ["selector", "navigation", "function"]

    def test_to_param_returns_valid_function_spec(self) -> None:
        tool = AdvancedBrowserTool()
        spec = tool.to_param()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "advanced_browser"
        assert "parameters" in spec["function"]
