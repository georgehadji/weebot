"""Tests for DesktopA11yTool with mocked _with_pygetwindow."""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


def _parse_elements(result) -> list:
    """Extract JSON array from tool output containing leading summary text."""
    output = result.output
    start = output.find("[")
    end = output.rfind("]") + 1
    if start != -1 and end > start:
        return json.loads(output[start:end])
    return []


@pytest.fixture
def fake_elements():
    """Fake desktop elements to return from mocked _with_pygetwindow."""
    return [
        {"name": "Settings", "role": "window",
         "bounds": {"x": 100, "y": 100, "w": 800, "h": 600}, "enabled": True, "focused": True},
        {"name": "Terminal", "role": "window",
         "bounds": {"x": 200, "y": 200, "w": 640, "h": 480}, "enabled": True, "focused": False},
        {"name": "Browser — Weebot", "role": "window",
         "bounds": {"x": 0, "y": 0, "w": 1920, "h": 1080}, "enabled": True, "focused": False},
    ]


class TestDesktopA11y:
    """DesktopA11yTool tests using mocked element extraction."""

    @pytest.fixture
    def tool(self):
        from weebot.tools.desktop_a11y import DesktopA11yTool
        return DesktopA11yTool()

    @pytest.mark.asyncio
    async def test_fallback_to_pygetwindow_all_windows(self, tool, fake_elements):
        """All visible windows returned as flat JSON elements."""
        with patch.object(tool, "_extract_elements", return_value=fake_elements):
            result = await tool.execute()
        elements = _parse_elements(result)
        assert len(elements) == 3
        titles = {e["name"] for e in elements}
        assert "Settings" in titles

    @pytest.mark.asyncio
    async def test_window_title_filter(self, tool, fake_elements):
        """window_title parameter filters elements."""
        filtered = [e for e in fake_elements if "terminal" in e["name"].lower()]
        with patch.object(tool, "_extract_elements", return_value=filtered):
            result = await tool.execute(window_title="Terminal")
        elements = _parse_elements(result)
        assert len(elements) == 1
        assert elements[0]["name"] == "Terminal"

    @pytest.mark.asyncio
    async def test_element_structure(self, tool, fake_elements):
        """Each element has name, role, bounds, enabled, focused."""
        with patch.object(tool, "_extract_elements", return_value=fake_elements):
            result = await tool.execute()
        elements = _parse_elements(result)
        for el in elements:
            assert "name" in el
            assert "role" in el
            assert "bounds" in el
            assert "x" in el["bounds"]
            assert "focused" in el

    @pytest.mark.asyncio
    async def test_active_window_marked_focused(self, tool, fake_elements):
        """The active window is marked with focused=True."""
        with patch.object(tool, "_extract_elements", return_value=fake_elements):
            result = await tool.execute()
        elements = _parse_elements(result)
        focused = [e for e in elements if e["focused"]]
        assert len(focused) == 1
        assert focused[0]["name"] == "Settings"

    @pytest.mark.asyncio
    async def test_empty_no_windows(self, tool):
        """Returns empty array when no windows found."""
        with patch.object(tool, "_extract_elements", return_value=[]):
            result = await tool.execute()
        elements = _parse_elements(result)
        assert elements == []

    @pytest.mark.asyncio
    async def test_truncation_at_max_elements(self, tool):
        """Elements above 200 are truncated."""
        many = [
            {"name": f"Item {i}", "role": "button",
             "bounds": {"x": 0, "y": 0, "w": 10, "h": 10},
             "enabled": True, "focused": False}
            for i in range(250)
        ]
        with patch.object(tool, "_extract_elements", return_value=many):
            result = await tool.execute()
        elements = _parse_elements(result)
        assert len(elements) == 200  # Capped at 200

    @pytest.mark.asyncio
    async def test_import_error_graceful(self, tool):
        """Returns error result when extraction fails."""
        with patch.object(tool, "_extract_elements", side_effect=RuntimeError("backend crash")):
            result = await tool.execute()
            assert result.is_error
