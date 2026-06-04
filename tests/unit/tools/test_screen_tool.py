"""Unit tests for ScreenCaptureTool."""
import pytest
from unittest.mock import patch, MagicMock
from weebot.tools.screen_tool import ScreenCaptureTool


class TestListScreens:
    def test_returns_list(self):
        mock_mss = MagicMock()
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_mss.return_value)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        mock_mss.return_value.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080}
        ]
        with patch("weebot.tools.screen_tool.mss", mock_mss):
            tool = ScreenCaptureTool()
            result = tool.list_screens()
        assert isinstance(result, list)

    def test_returns_dict_per_monitor(self):
        mock_mss = MagicMock()
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_mss.return_value)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        mock_mss.return_value.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080}
        ]
        with patch("weebot.tools.screen_tool.mss", mock_mss):
            tool = ScreenCaptureTool()
            screens = tool.list_screens()
        for s in screens:
            assert "index" in s
            assert "width" in s
            assert "height" in s


class TestCapture:
    def _make_mock_mss(self):
        mock_img = MagicMock()
        mock_img.rgb = b"\xff\x00\x00" * 100
        mock_img.width = 10
        mock_img.height = 10
        mock_ctx = MagicMock()
        mock_ctx.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_ctx.grab.return_value = mock_img
        mock_mss = MagicMock()
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        return mock_mss

    def test_capture_returns_success(self):
        with patch("weebot.tools.screen_tool.mss", self._make_mock_mss()):
            with patch("weebot.tools.screen_tool.Image"):
                tool = ScreenCaptureTool()
                result = tool.capture(monitor_index=0)
        assert result["success"] is True

    def test_capture_result_has_data_key(self):
        with patch("weebot.tools.screen_tool.mss", self._make_mock_mss()):
            with patch("weebot.tools.screen_tool.Image"):
                tool = ScreenCaptureTool()
                result = tool.capture(monitor_index=0)
        assert "data" in result

    def test_capture_invalid_index_returns_error(self):
        mock_mss = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_mss.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)
        with patch("weebot.tools.screen_tool.mss", mock_mss):
            tool = ScreenCaptureTool()
            result = tool.capture(monitor_index=999)
        assert result["success"] is False
        assert "error" in result["output"].lower() or "invalid" in result["output"].lower()
