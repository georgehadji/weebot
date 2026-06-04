"""WindowsDesktopAdapter — system tray, global hotkey, and overlay for Windows.

Implements ``DesktopPort`` using:
- **pystray** for the system tray icon (color-coded status).
- **tkinter** for the quick-prompt overlay window.
- **keyboard** for the global ``Win + Alt + W`` hotkey.

All optional dependencies degrade gracefully with clear error messages.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import queue
from pathlib import Path
from typing import Any, Optional

from weebot.application.ports.desktop_port import (
    DesktopPort,
    DesktopPrompt,
    DesktopResponse,
    DesktopStatus,
)

logger = logging.getLogger(__name__)

# ── optional dependency flags ───────────────────────────────────────

_PYSTRAY_AVAILABLE = False
_TKINTER_AVAILABLE = False
_KEYBOARD_AVAILABLE = False

try:
    import pystray  # type: ignore[import-untyped]
    _PYSTRAY_AVAILABLE = True
except ImportError:
    pystray = None  # type: ignore[assignment]

try:
    import tkinter as tk
    import tkinter.scrolledtext as tkst
    _TKINTER_AVAILABLE = True
except ImportError:
    tk = None  # type: ignore[assignment]

try:
    import keyboard  # type: ignore[import-untyped]
    _KEYBOARD_AVAILABLE = True
except ImportError:
    keyboard = None  # type: ignore[assignment]

from PIL import Image, ImageDraw


# ── constants ───────────────────────────────────────────────────────

HOTKEY_COMBO = "win+alt+w"
OVERLAY_TITLE = "weebot Quick Prompt"
OVERLAY_WIDTH = 600
OVERLAY_HEIGHT = 300


class WindowsDesktopAdapter(DesktopPort):
    """Desktop companion for Windows using system tray + hotkey + overlay.

    Args:
        loop: Optional asyncio event loop.  Uses ``asyncio.get_event_loop()``
            if not provided.
    """

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._status = DesktopStatus.DISCONNECTED

        # Tray state
        self._icon: Optional["pystray.Icon"] = None
        self._icon_thread: Optional[threading.Thread] = None

        # Overlay state
        self._overlay_win: Optional["tk.Toplevel"] = None
        self._overlay_queue: queue.Queue[Optional[str]] = queue.Queue()
        self._tk_root: Optional["tk.Tk"] = None
        self._tk_thread: Optional[threading.Thread] = None

        # Running flag
        self._running = False

        # Thread safety for _icon shared between async and pystray threads
        self._icon_lock: threading.Lock = threading.Lock()
        self._icon_ready: threading.Event = threading.Event()

        self._check_dependencies()

    @staticmethod
    def _check_dependencies() -> None:
        """Log warnings for missing optional dependencies."""
        if not _PYSTRAY_AVAILABLE:
            logger.info("pystray not available — install with: pip install pystray")
        if not _TKINTER_AVAILABLE:
            logger.info("tkinter not available — install Python with tk support")
        if not _KEYBOARD_AVAILABLE:
            logger.info("keyboard not available — install with: pip install keyboard")

    # ── abstract implementations ────────────────────────────────────

    async def start(self) -> None:
        """Start the desktop companion.

        Launches the system tray icon in a background thread and
        registers the global hotkey.
        """
        if self._running:
            logger.warning("WindowsDesktopAdapter is already running")
            return
        self._icon_ready.clear()
        self._icon_lock = threading.Lock()
        self._running = True

        self.set_status(DesktopStatus.CONNECTING)

        # Start tray icon in background thread
        if _PYSTRAY_AVAILABLE:
            self._icon_thread = threading.Thread(
                target=self._run_tray,
                daemon=True,
                name="weebot-tray",
            )
            self._icon_thread.start()
            logger.info("System tray icon started")
        else:
            logger.warning("No tray icon — pystray not installed")

        # Start tkinter root in background thread
        if _TKINTER_AVAILABLE:
            self._tk_thread = threading.Thread(
                target=self._run_tk,
                daemon=True,
                name="weebot-tk",
            )
            self._tk_thread.start()
            logger.info("Tkinter overlay thread started")
        else:
            logger.warning("No overlay — tkinter not available")

        # Register global hotkey
        if _KEYBOARD_AVAILABLE and _TKINTER_AVAILABLE:
            try:
                keyboard.add_hotkey(HOTKEY_COMBO, self._on_hotkey)
                logger.info("Global hotkey %s registered", HOTKEY_COMBO)
            except Exception as exc:
                logger.warning("Failed to register hotkey %s: %s", HOTKEY_COMBO, exc)
        else:
            logger.warning("No hotkey — keyboard library not available")

        self.set_status(DesktopStatus.CONNECTED)

    async def stop(self) -> None:
        """Stop the companion and clean up OS resources."""
        self._running = False

        # Unregister hotkey
        if _KEYBOARD_AVAILABLE:
            try:
                keyboard.remove_hotkey(HOTKEY_COMBO)
            except Exception:
                pass

        # Stop tray icon
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

        # Close overlay
        if self._overlay_win is not None:
            try:
                self._overlay_win.quit()
            except Exception:
                pass
            self._overlay_win = None

        # Quit tkinter root
        if self._tk_root is not None:
            try:
                self._tk_root.quit()
            except Exception:
                pass
            self._tk_root = None

        self.set_status(DesktopStatus.DISCONNECTED)
        logger.info("WindowsDesktopAdapter stopped")

    def set_status(self, status: DesktopStatus) -> None:
        """Update the system tray icon color."""
        self._status = status
        if _PYSTRAY_AVAILABLE:
            # Wait briefly for the tray icon to be created (avoids race on startup)
            ready = self._icon_ready.wait(timeout=2.0)
            if ready:
                with self._icon_lock:
                    if self._icon is not None:
                        self._icon.icon = _generate_icon_image(
                            _STATUS_COLORS.get(status, "gray"),
                        )
                        self._icon.title = f"weebot — {status.value}"

    async def show_overlay(self) -> Optional[DesktopPrompt]:
        """Open the overlay and wait for user input (blocking)."""
        if not _TKINTER_AVAILABLE:
            logger.warning("Cannot show overlay — tkinter not available")
            return None

        # Signal the tkinter thread to show the overlay
        self._overlay_queue.put("SHOW")

        # Wait for the response (blocking in async context)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._overlay_queue.get)

        if result is None:
            return None
        return DesktopPrompt(text=result)

    async def show_response(self, response: DesktopResponse) -> None:
        """Display a response in the overlay."""
        if self._overlay_win is not None and _TKINTER_AVAILABLE:
            self._overlay_queue.put(f"RESPONSE:{response.text}")

    # ── internal: tray ──────────────────────────────────────────────

    def _run_tray(self) -> None:
        """Run the pystray icon (blocking — runs in daemon thread)."""
        icon_image = _generate_icon_image(
            _STATUS_COLORS.get(self._status, "gray"),
        )
        with self._icon_lock:
            self._icon = pystray.Icon(
            name="weebot",
            icon=icon_image,
            title="weebot Agent",
            menu=pystray.Menu(
                pystray.MenuItem(
                    f"Status: {self._status.value.capitalize()}",
                    None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quick Prompt", self._on_tray_prompt),
                pystray.MenuItem("Quit", self._on_tray_quit),
            ),
        )
        self._icon_ready.set()
        self._icon.run()

    def _on_tray_prompt(self, icon: Any, item: Any) -> None:
        """Tray menu callback — triggers the overlay."""
        asyncio.run_coroutine_threadsafe(
            self.show_overlay(), self._loop,
        )

    def _on_tray_quit(self, icon: Any, item: Any) -> None:
        """Tray menu callback — stops everything."""
        asyncio.run_coroutine_threadsafe(
            self.stop(), self._loop,
        )

    # ── internal: overlay ───────────────────────────────────────────

    def _run_tk(self) -> None:
        """Run the tkinter root (blocking — runs in daemon thread).

        Creates a hidden root window and starts the tkinter event loop.
        Overlays are created as child ``Toplevel`` windows on demand.
        """
        self._tk_root = tk.Tk() if tk else None  # type: ignore[union-attr]
        if self._tk_root is None:
            return
        self._tk_root.withdraw()  # Keep root hidden
        self._tk_root.title(OVERLAY_TITLE)

        # Poll the overlay queue periodically
        self._poll_overlay_queue()
        self._tk_root.mainloop()

    def _poll_overlay_queue(self) -> None:
        """Periodically check the overlay queue for commands."""
        if not self._running or self._tk_root is None:
            return

        try:
            command = self._overlay_queue.get_nowait()
            if command == "SHOW":
                self._create_overlay_window()
            elif command and command.startswith("RESPONSE:"):
                text = command[len("RESPONSE:"):]
                self._update_overlay_text(text)
        except queue.Empty:
            pass
        finally:
            # Schedule next poll (10 times per second)
            if self._tk_root:
                try:
                    self._tk_root.after(100, self._poll_overlay_queue)
                except tk.TclError:
                    pass

    def _create_overlay_window(self) -> None:
        """Create (or reveal) the tkinter overlay window."""
        if self._tk_root is None:
            return

        if self._overlay_win is not None:
            try:
                self._overlay_win.deiconify()
                self._overlay_win.lift()
                self._overlay_win.focus_force()
                return
            except tk.TclError:
                self._overlay_win = None

        win = tk.Toplevel(self._tk_root)
        win.title(OVERLAY_TITLE)
        win.geometry(f"{OVERLAY_WIDTH}x{OVERLAY_HEIGHT}")
        win.resizable(True, True)

        # Center on screen
        win.update_idletasks()
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = (screen_w - OVERLAY_WIDTH) // 2
        y = (screen_h - OVERLAY_HEIGHT) // 2
        win.geometry(f"+{x}+{y}")

        # Prompt label + input
        tk.Label(win, text="Prompt:", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 2),
        )
        entry_var = tk.StringVar()
        entry = tk.Entry(win, textvariable=entry_var, font=("Segoe UI", 11))
        entry.pack(fill="x", padx=10, pady=(0, 10))
        entry.focus_set()

        # Submit button (Enter also submits)
        submit_btn = tk.Button(
            win, text="Submit (Enter)",
            command=lambda: self._submit_prompt(entry_var),
        )
        submit_btn.pack(pady=(0, 5))

        # Response area
        tk.Label(win, text="Response:", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=10, pady=(5, 2),
        )
        response_text = tkst.ScrolledText(
            win, height=6, wrap=tk.WORD, font=("Segoe UI", 10),
        )
        response_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        response_text.config(state=tk.DISABLED)

        win.response_text = response_text  # type: ignore[attr-defined]
        win.protocol("WM_DELETE_WINDOW", lambda: self._dismiss_overlay(win))

        # Enter key submits
        win.bind("<Return>", lambda e: self._submit_prompt(entry_var))
        win.bind("<Escape>", lambda e: self._dismiss_overlay(win))

        self._overlay_win = win

    def _submit_prompt(self, entry_var: "tk.StringVar") -> None:
        """Submit the current prompt text and close the overlay."""
        text = entry_var.get().strip()
        if not text:
            return
        if self._overlay_win:
            self._overlay_win.withdraw()
        self._overlay_queue.put(text)

    def _dismiss_overlay(self, win: "tk.Toplevel") -> None:
        """Dismiss the overlay without submitting."""
        win.withdraw()
        self._overlay_queue.put(None)

    def _update_overlay_text(self, text: str) -> None:
        """Append response text to the overlay's response area."""
        if self._overlay_win is None:
            return
        try:
            txt_widget = getattr(self._overlay_win, "response_text", None)
            if txt_widget:
                txt_widget.config(state=tk.NORMAL)
                txt_widget.delete("1.0", tk.END)
                txt_widget.insert(tk.END, text)
                txt_widget.config(state=tk.DISABLED)
        except tk.TclError:
            pass

    # ── internal: hotkey callback ───────────────────────────────────

    def _on_hotkey(self) -> None:
        """Global hotkey callback — triggers overlay from any thread."""
        asyncio.run_coroutine_threadsafe(
            self.show_overlay(), self._loop,
        )


# ── module-level helpers ────────────────────────────────────────────

_STATUS_COLORS = {
    DesktopStatus.CONNECTED: "green",
    DesktopStatus.CONNECTING: "orange",
    DesktopStatus.DISCONNECTED: "gray",
    DesktopStatus.ERROR: "red",
}


def _generate_icon_image(color: str) -> "Image.Image":
    """Draw a 64x64 circle icon in the given color."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        [(margin, margin), (size - margin, size - margin)],
        fill=color,
    )
    return img
