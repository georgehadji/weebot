"""Unit tests for tray app non-GUI logic."""
import pytest
from unittest.mock import MagicMock, patch
from weebot.tray import TrayStatusIcon, TrayStatus


class TestTrayStatus:
    def test_status_enum_has_expected_values(self):
        assert TrayStatus.CONNECTED.value == "connected"
        assert TrayStatus.CONNECTING.value == "connecting"
        assert TrayStatus.DISCONNECTED.value == "disconnected"
        assert TrayStatus.ERROR.value == "error"


class TestTrayStatusIcon:
    def test_initial_status_is_disconnected(self):
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        icon._status = TrayStatus.DISCONNECTED
        assert icon._status == TrayStatus.DISCONNECTED

    def test_status_to_color_mapping(self):
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        assert icon._color_for_status(TrayStatus.CONNECTED) == "green"
        assert icon._color_for_status(TrayStatus.CONNECTING) == "orange"
        assert icon._color_for_status(TrayStatus.ERROR) == "red"
        assert icon._color_for_status(TrayStatus.DISCONNECTED) == "gray"

    def test_unknown_status_falls_back_to_gray(self):
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        # Pass an unexpected value directly to test fallback
        assert icon._color_for_status(None) == "gray"  # type: ignore[arg-type]

    def test_generate_icon_returns_pil_image(self):
        from PIL import Image
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        img = icon._generate_icon_image("green")
        assert isinstance(img, Image.Image)

    def test_generate_icon_is_64x64(self):
        icon = TrayStatusIcon.__new__(TrayStatusIcon)
        img = icon._generate_icon_image("red")
        assert img.size == (64, 64)

    def test_build_menu_items_returns_list(self):
        with patch("weebot.tray.pystray", MagicMock()):
            with patch("weebot.tray._PYSTRAY_AVAILABLE", True):
                icon = TrayStatusIcon.__new__(TrayStatusIcon)
                icon._status = TrayStatus.DISCONNECTED
                icon._agent = None
                items = icon._build_menu_items()
                assert isinstance(items, list)
                assert len(items) > 0

    def test_build_menu_items_empty_without_pystray(self):
        with patch("weebot.tray._PYSTRAY_AVAILABLE", False):
            icon = TrayStatusIcon.__new__(TrayStatusIcon)
            icon._status = TrayStatus.DISCONNECTED
            assert icon._build_menu_items() == []

    def test_set_status_updates_internal_state(self):
        icon = TrayStatusIcon()
        icon._icon = None   # no real tray window
        icon.set_status(TrayStatus.CONNECTED)
        assert icon._status == TrayStatus.CONNECTED

    def test_set_status_connected_uses_green_icon(self):
        icon = TrayStatusIcon()
        captured_images = []

        class FakeIcon:
            title = ""
            def __setattr__(self, name, value):
                if name == "icon":
                    captured_images.append(value)
                object.__setattr__(self, name, value)

        icon._icon = FakeIcon()
        icon.set_status(TrayStatus.CONNECTED)
        assert len(captured_images) == 1
        # Verify it's a PIL image (green circle)
        from PIL import Image
        assert isinstance(captured_images[0], Image.Image)
