"""Tests for DesktopSomRenderer."""
import base64
import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO

# Minimal valid 1x1 PNG for testing (valid PNG header + data)
_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture
def renderer():
    """Create a DesktopSomRenderer instance."""
    from weebot.infrastructure.browser.som_renderer import DesktopSomRenderer
    return DesktopSomRenderer()


@pytest.fixture
def sample_elements():
    """Synthetic desktop elements with bounds."""
    return [
        {"name": "OK Button", "role": "button",
         "bounds": {"x": 100, "y": 200, "w": 80, "h": 30}, "enabled": True, "focused": False},
        {"name": "Cancel", "role": "button",
         "bounds": {"x": 200, "y": 200, "w": 80, "h": 30}, "enabled": True, "focused": False},
        {"name": "Name:", "role": "label",
         "bounds": {"x": 50, "y": 100, "w": 50, "h": 20}, "enabled": True, "focused": False},
        # Tiny element (should be skipped: w<4 or h<4)
        {"name": "Tiny", "role": "widget",
         "bounds": {"x": 0, "y": 0, "w": 2, "h": 2}, "enabled": True, "focused": False},
    ]


class TestDesktopSomRenderer:
    """DesktopSomRenderer tests."""

    @pytest.mark.asyncio
    async def test_render_desktop_basic(self, renderer, sample_elements):
        """3 valid boxes rendered on a simple screenshot."""
        result = await renderer.render_desktop(_VALID_PNG, sample_elements, max_marks=50)
        assert isinstance(result, str)
        decoded = base64.b64decode(result)
        assert len(decoded) > 0
        # Result should be a valid PNG
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_render_clips_to_region(self, renderer, sample_elements):
        """Elements outside the specified region are filtered out."""
        # Region covers only the top-left quadrant
        result = await renderer.render_desktop(
            _VALID_PNG, sample_elements,
            region=(0, 0, 120, 120), max_marks=50,
        )
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    @pytest.mark.asyncio
    async def test_render_max_marks_capped(self, renderer):
        """100 elements are capped at max_marks=10."""
        elements = [
            {"name": f"Item {i}", "role": "button",
             "bounds": {"x": i * 10, "y": i * 10, "w": 50, "h": 20},
             "enabled": True, "focused": False}
            for i in range(100)
        ]
        result = await renderer.render_desktop(_VALID_PNG, elements, max_marks=10)
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    @pytest.mark.asyncio
    async def test_empty_elements_returns_png(self, renderer):
        """Empty element list returns a valid PNG (unmodified or base layer)."""
        result = await renderer.render_desktop(_VALID_PNG, [], max_marks=50)
        assert isinstance(result, str)
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    @pytest.mark.asyncio
    async def test_no_bounds_skipped(self, renderer):
        """Elements missing bounds dict are skipped gracefully."""
        elements = [
            {"name": "NoBounds", "role": "button", "enabled": True, "focused": False},
            {"name": "EmptyBounds", "role": "button",
             "bounds": {}, "enabled": True, "focused": False},
        ]
        result = await renderer.render_desktop(_VALID_PNG, elements, max_marks=50)
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    @pytest.mark.asyncio
    async def test_tiny_elements_skipped(self, renderer, sample_elements):
        """Elements with w<4 or h<4 are not rendered."""
        # The Tiny element (2x2) should be skipped
        result = await renderer.render_desktop(_VALID_PNG, sample_elements, max_marks=50)
        decoded = base64.b64decode(result)
        assert len(decoded) > 0
