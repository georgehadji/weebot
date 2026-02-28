"""System tray application for weebot (pystray-based).

Run with:
    python -m weebot.tray
or:
    python run.py --tray
"""
from __future__ import annotations
import asyncio
import threading
from enum import Enum
from typing import List, Optional

try:
    import pystray
    _PYSTRAY_AVAILABLE = True
except ImportError:
    pystray = None  # type: ignore[assignment]
    _PYSTRAY_AVAILABLE = False

from PIL import Image, ImageDraw


class TrayStatus(Enum):
    CONNECTED    = "connected"
    CONNECTING   = "connecting"
    DISCONNECTED = "disconnected"
    ERROR        = "error"


class TrayStatusIcon:
    """Manages a system tray icon that reflects weebot agent status."""

    STATUS_COLORS = {
        TrayStatus.CONNECTED:    "green",
        TrayStatus.CONNECTING:   "orange",
        TrayStatus.DISCONNECTED: "gray",
        TrayStatus.ERROR:        "red",
    }

    def __init__(self) -> None:
        self._status = TrayStatus.DISCONNECTED
        self._agent = None
        self._icon = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------ #
    # Non-GUI helpers (fully unit-testable without pystray)               #
    # ------------------------------------------------------------------ #

    def _color_for_status(self, status: TrayStatus) -> str:
        return self.STATUS_COLORS.get(status, "gray")

    def _generate_icon_image(self, color: str) -> Image.Image:
        """Draw a 64×64 circle icon in the given color."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([(4, 4), (size - 4, size - 4)], fill=color)
        return img

    def _build_menu_items(self) -> list:
        if not _PYSTRAY_AVAILABLE:
            return []
        return [
            pystray.MenuItem(
                f"Status: {self._status.value.capitalize()}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Status", self._on_show_status),
            pystray.MenuItem("Quit", self._on_quit),
        ]

    # ------------------------------------------------------------------ #
    # GUI callbacks                                                       #
    # ------------------------------------------------------------------ #

    def _on_show_status(self, icon, item) -> None:
        if self._agent:
            status = self._agent.get_status()
            print(f"[weebot] {status}")

    def _on_quit(self, icon, item) -> None:
        icon.stop()

    def set_status(self, status: TrayStatus) -> None:
        self._status = status
        if self._icon:
            self._icon.icon = self._generate_icon_image(
                self._color_for_status(status)
            )
            self._icon.title = f"weebot — {status.value}"

    # ------------------------------------------------------------------ #
    # Entry point                                                         #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Start the tray icon (blocking — call from main thread)."""
        if not _PYSTRAY_AVAILABLE:
            print("pystray not installed. Install with: pip install pystray")
            return

        icon_image = self._generate_icon_image(
            self._color_for_status(self._status)
        )
        self._icon = pystray.Icon(
            name="weebot",
            icon=icon_image,
            title="weebot Agent",
            menu=pystray.Menu(*self._build_menu_items()),
        )
        self._icon.run()


def main() -> None:
    """Entry point for `python -m weebot.tray`."""
    tray = TrayStatusIcon()
    tray.set_status(TrayStatus.CONNECTING)
    tray.run()


if __name__ == "__main__":
    main()
