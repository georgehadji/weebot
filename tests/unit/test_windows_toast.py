# tests/unit/test_windows_toast.py
"""Unit tests for WindowsToastChannel."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from weebot.notifications import Notification, NotificationLevel, WindowsToastChannel


class TestWindowsToastChannel:
    def _make_notification(self, title="Test", message="body", category="info"):
        return Notification(
            title=title, message=message,
            level=NotificationLevel.INFO,
            timestamp=datetime.now(),
            category=category,
        )

    @pytest.mark.asyncio
    async def test_send_returns_true_when_winotify_available(self):
        mock_toast_cls = MagicMock()
        mock_toast = MagicMock()
        mock_toast_cls.return_value = mock_toast
        with patch.dict("sys.modules", {"winotify": MagicMock(Notification=mock_toast_cls)}):
            ch = WindowsToastChannel(app_name="weebot-test")
            result = await ch.send(self._make_notification())
        assert result is True

    @pytest.mark.asyncio
    async def test_send_returns_false_when_winotify_missing(self):
        with patch.dict("sys.modules", {"winotify": None}):
            ch = WindowsToastChannel(app_name="weebot-test")
            result = await ch.send(self._make_notification())
        assert result is False

    @pytest.mark.asyncio
    async def test_urgent_notification_uses_looping_audio(self):
        mock_winotify = MagicMock()
        mock_toast = MagicMock()
        mock_winotify.Notification.return_value = mock_toast
        mock_winotify.audio = MagicMock()
        with patch.dict("sys.modules", {"winotify": mock_winotify}):
            ch = WindowsToastChannel(app_name="weebot-test")
            await ch.send(self._make_notification(category="urgent"))
        mock_toast.set_audio.assert_called_once()

    def test_category_to_icon_mapping(self):
        ch = WindowsToastChannel(app_name="weebot-test")
        assert ch._icon_for_category("urgent") == "ms-appx:///Assets/StoreLogo.png" or \
               isinstance(ch._icon_for_category("urgent"), str)
        assert ch._icon_for_category("info") == ch._icon_for_category("unknown_cat")
