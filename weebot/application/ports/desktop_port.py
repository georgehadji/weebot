"""DesktopPort — system-tray and hotkey integration for desktop OS.

Defines a platform-agnostic abstraction for desktop companion features:
system tray icon with status indication, global hotkey listener, and
a quick-prompt overlay window.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DesktopStatus(Enum):
    """Runtime status reflected in the system tray icon."""
    CONNECTED = "connected"
    CONNECTING = "connecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class DesktopPrompt:
    """A prompt submitted from the desktop overlay."""
    text: str
    session_id: Optional[str] = None


@dataclass
class DesktopResponse:
    """A response to display in the desktop overlay."""
    text: str
    success: bool = True
    tool_calls: int = 0


class DesktopPort(ABC):
    """Abstraction for desktop OS integration.

    Implementations provide system tray, global hotkey, and overlay
    window functionality.  The default implementation targets Windows
    via ``pystray`` + ``tkinter`` + ``keyboard``.
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the desktop companion.

        Creates the system tray icon, registers the global hotkey,
        and begins the event loop.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the companion and clean up OS resources.

        Removes the tray icon, unregisters the hotkey, closes the
        overlay window if open.
        """
        ...

    @abstractmethod
    def set_status(self, status: DesktopStatus) -> None:
        """Update the system tray icon status color.

        Args:
            status: New runtime status to reflect.
        """
        ...

    @abstractmethod
    async def show_overlay(self) -> Optional[DesktopPrompt]:
        """Open the quick-prompt overlay and wait for user input.

        Returns:
            ``DesktopPrompt`` if the user submitted text via Enter,
            ``None`` if the overlay was dismissed (Escape).
        """
        ...

    @abstractmethod
    async def show_response(self, response: DesktopResponse) -> None:
        """Display a response in the overlay.

        Args:
            response: The response text and metadata to show.
        """
        ...
