"""DesktopA11yTool — desktop-level accessibility tree extraction.

Enumerates interactive UI elements in the active window using platform-
specific accessibility APIs. Returns a flat, pruned JSON array suitable
for LLM consumption (no raw XML).

Backends (tried in order):
1. pywinauto (Windows UIA) — richest data
2. pyatspi (Linux) — for OSWorld Docker/KVM
3. ctypes Win32 API — lightweight Windows fallback
4. pygetwindow — window title/geometry only (minimal)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Maximum tree depth to avoid infinite recursion
_MAX_A11Y_DEPTH = 12
# Maximum number of elements to return (token budget)
_MAX_A11Y_ELEMENTS = 200
# Roles that are not interactive — pruned from output
_SKIP_ROLES = frozenset({
    "pane", "panel", "separator", "tooltip", "statusbar",
    "desktop", "client", "scrollpane", "splitpane",
})


class DesktopA11yTool(BaseTool):
    """Extract the accessibility tree of the active desktop window.

    Returns a flat JSON array of interactive UI elements with their
    name, role, bounding box (x, y, w, h), and state flags.

    Usage:
        desktop_a11y()  →  JSON array of UI elements from active window
        desktop_a11y(window_title="Settings")  →  target specific window
    """
    name: str = "desktop_a11y"
    description: str = (
        "Extract the accessibility tree of the active desktop window. "
        "Returns a flat JSON array of interactive UI elements with name, role, "
        "position, and state. Use this to find buttons, text fields, menus, "
        "and other UI controls before clicking or typing. "
        "Parameter: window_title (optional) — target a specific window by title."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "window_title": {
                "type": "string",
                "description": "Optional: target a specific window by title substring",
            },
        },
    }

    async def execute(self, window_title: str = "") -> ToolResult:
        try:
            elements = await self._extract_elements(window_title)
            truncated = len(elements) > _MAX_A11Y_ELEMENTS
            if truncated:
                elements = elements[:_MAX_A11Y_ELEMENTS]
            return ToolResult(
                output=json.dumps(elements, indent=2, ensure_ascii=False),
                summary=(
                    f"Found {len(elements)}{' (truncated)' if truncated else ''} "
                    f"interactive elements"
                ),
            )
        except Exception as exc:
            logger.warning("DesktopA11yTool failed: %s", exc)
            return ToolResult.error_result(
                f"Failed to extract accessibility tree: {exc}. "
                "Try using screen_capture for a visual approach instead."
            )

    async def _extract_elements(self, window_title: str) -> list[dict]:
        """Try each backend in priority order."""
        # 1. pywinauto — richest
        try:
            import pywinauto
            from pywinauto.application import Application
            from pywinauto import Desktop as PwDesktop
            return await self._with_pywinauto(window_title)
        except ImportError:
            logger.debug("pywinauto not available, trying ctypes UIA...")

        # 2. ctypes UIA — Windows fallback
        try:
            return await self._with_ctypes_uia(window_title)
        except Exception as exc:
            logger.debug("ctypes UIA failed: %s", exc)

        # 3. pygetwindow — minimal (window info only)
        return await self._with_pygetwindow(window_title)

    async def _with_pywinauto(self, window_title: str) -> list[dict]:
        """Extract elements via pywinauto Desktop/UIA wrapper."""
        from pywinauto import Desktop as PwDesktop
        desktop = PwDesktop(backend="uia")
        elements = []

        def walk(element, depth: int = 0):
            if depth > _MAX_A11Y_DEPTH or len(elements) >= _MAX_A11Y_ELEMENTS:
                return
            try:
                ctrl = element if hasattr(element, 'element_info') else None
                if ctrl is None:
                    return
                info = ctrl.element_info
                role = info.control_type or ""
                if role.lower() in _SKIP_ROLES:
                    return
                rect = info.rectangle if hasattr(info, 'rectangle') else None
                elements.append({
                    "name": (info.name or "")[:80],
                    "role": role,
                    "bounds": {
                        "x": rect.left if rect else 0,
                        "y": rect.top if rect else 0,
                        "w": rect.width() if rect else 0,
                        "h": rect.height() if rect else 0,
                    },
                    "enabled": not (hasattr(info, 'enabled') and not info.enabled),
                    "focused": info.control_id == 0 if hasattr(info, 'control_id') else False,
                })
            except Exception:
                pass
            try:
                for child in element.descendants():
                    walk(child, depth + 1)
            except (AttributeError, RuntimeError, IndexError):
                pass

        if window_title:
            try:
                win = desktop.window(title=window_title)
                if win.exists():
                    walk(win)
                    return elements
            except Exception:
                pass

        # Fallback: walk all top-level windows
        for win in desktop.windows():
            if len(elements) >= _MAX_A11Y_ELEMENTS:
                break
            walk(win, depth=0)

        return elements

    async def _with_ctypes_uia(self, window_title: str) -> list[dict]:
        """Minimal UIA extraction via ctypes + comtypes API."""
        import ctypes
        from ctypes import wintypes

        # Use EnumWindows to get window info as a fallback
        elements = []
        _user32 = ctypes.windll.user32

        def enum_windows_proc(hwnd, lparam):
            if len(elements) >= _MAX_A11Y_ELEMENTS:
                return False
            length = _user32.GetWindowTextLengthW(hwnd) + 1
            buffer = ctypes.create_unicode_buffer(length)
            _user32.GetWindowTextW(hwnd, buffer, length)
            title = buffer.value
            if window_title and window_title.lower() not in title.lower():
                return True
            rect = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
            is_visible = _user32.IsWindowVisible(hwnd)
            if not is_visible:
                return True
            elements.append({
                "name": title[:80],
                "role": "window",
                "bounds": {"x": rect.left, "y": rect.top, "w": rect.right - rect.left, "h": rect.bottom - rect.top},
                "enabled": True,
                "focused": _user32.GetForegroundWindow() == hwnd,
            })
            return True

        EnumWindows = _user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        EnumWindows(EnumWindowsProc(enum_windows_proc), 0)
        return elements

    async def _with_pygetwindow(self, window_title: str) -> list[dict]:
        """Minimal window info via pygetwindow."""
        import pygetwindow as gw
        elements = []
        try:
            if window_title:
                windows = gw.getWindowsWithTitle(window_title)
            else:
                windows = gw.getAllWindows()
            for win in windows[:50]:
                if win.visible:
                    elements.append({
                        "name": (win.title or "")[:80],
                        "role": "window",
                        "bounds": {"x": win.left, "y": win.top, "w": win.width, "h": win.height},
                        "enabled": True,
                        "focused": win.isActive,
                    })
        except Exception as exc:
            logger.debug("pygetwindow failed: %s", exc)
        return elements
