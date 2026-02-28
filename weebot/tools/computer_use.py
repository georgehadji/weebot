"""Computer use tools: mouse, keyboard, OCR, element detection."""
from __future__ import annotations

import asyncio
import base64
import time
from io import BytesIO
from typing import ClassVar, Literal, Optional

import pyautogui
from PIL import Image, ImageDraw

from weebot.tools.base import BaseTool, ToolResult


class ComputerUseTool(BaseTool):
    """Interactive computer control: mouse, keyboard, pointer tracking."""

    name: str = "computer_use"
    description: str = (
        "Control the computer: move mouse, click, type, press keys. "
        "Useful for desktop automation, form filling, web interactions."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "move_mouse",
                    "click",
                    "double_click",
                    "drag",
                    "type",
                    "press_key",
                    "key_down",
                    "key_up",
                    "get_mouse_position",
                ],
                "description": "Action to perform",
            },
            "x": {
                "type": "integer",
                "description": "X coordinate (pixels from left)",
            },
            "y": {
                "type": "integer",
                "description": "Y coordinate (pixels from top)",
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default: left)",
            },
            "text": {
                "type": "string",
                "description": "Text to type",
            },
            "key": {
                "type": "string",
                "description": "Key name (e.g., 'enter', 'tab', 'backspace', 'ctrl', 'shift')",
            },
            "duration": {
                "type": "number",
                "description": "Duration in seconds (for drag, key hold)",
            },
            "interval": {
                "type": "number",
                "description": "Interval between key presses (seconds)",
            },
            "modifiers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Modifier keys: ['ctrl', 'shift', 'alt', 'win']",
            },
        },
        "required": ["action"],
    }

    # Safe key names (prevent injection) - letters a-z, numbers 0-9, and special keys
    SAFE_KEYS: ClassVar[set[str]] = {
        "enter", "return", "tab", "backspace", "delete", "escape",
        "up", "down", "left", "right",
        "home", "end", "pageup", "pagedown",
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
        "insert", "space", "pause", "printscreen",
        "ctrl", "shift", "alt", "win", "command", "option",
        *[chr(i) for i in range(ord('a'), ord('z') + 1)],  # a-z
        *[str(i) for i in range(10)],  # 0-9
    }

    async def execute(
        self,
        action: str,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        text: Optional[str] = None,
        key: Optional[str] = None,
        duration: float = 0.5,
        interval: float = 0.05,
        modifiers: Optional[list[str]] = None,
        **_,
    ) -> ToolResult:
        """Execute computer control action."""
        try:
            modifiers = modifiers or []

            if action == "move_mouse":
                if x is None or y is None:
                    return ToolResult(output="", error="x and y required for move_mouse")
                pyautogui.moveTo(x, y, duration=0.25)
                return ToolResult(output=f"Moved mouse to ({x}, {y})")

            elif action == "click":
                if x is None or y is None:
                    return ToolResult(output="", error="x and y required for click")
                pyautogui.click(x, y, button=button)
                return ToolResult(output=f"Clicked at ({x}, {y}) with {button} button")

            elif action == "double_click":
                if x is None or y is None:
                    return ToolResult(output="", error="x and y required for double_click")
                pyautogui.doubleClick(x, y)
                return ToolResult(output=f"Double-clicked at ({x}, {y})")

            elif action == "drag":
                if x is None or y is None:
                    return ToolResult(output="", error="x and y required for drag")
                # Get current position
                start_x, start_y = pyautogui.position()
                pyautogui.drag(x - start_x, y - start_y, duration=duration, button=button)
                return ToolResult(
                    output=f"Dragged from ({start_x}, {start_y}) to ({x}, {y})"
                )

            elif action == "type":
                if text is None:
                    return ToolResult(output="", error="text required for type")
                pyautogui.write(text, interval=interval)
                return ToolResult(output=f"Typed: {text[:50]}...")

            elif action == "press_key":
                if key is None:
                    return ToolResult(output="", error="key required for press_key")
                key_lower = key.lower()
                if key_lower not in self.SAFE_KEYS:
                    return ToolResult(output="", error=f"Unsafe key: {key}")

                # Handle modifiers
                if modifiers:
                    self._press_with_modifiers(key_lower, modifiers)
                else:
                    pyautogui.press(key_lower)
                return ToolResult(output=f"Pressed key: {key}")

            elif action == "key_down":
                if key is None:
                    return ToolResult(output="", error="key required for key_down")
                key_lower = key.lower()
                if key_lower not in self.SAFE_KEYS:
                    return ToolResult(output="", error=f"Unsafe key: {key}")
                pyautogui.keyDown(key_lower)
                return ToolResult(output=f"Key down: {key}")

            elif action == "key_up":
                if key is None:
                    return ToolResult(output="", error="key required for key_up")
                key_lower = key.lower()
                if key_lower not in self.SAFE_KEYS:
                    return ToolResult(output="", error=f"Unsafe key: {key}")
                pyautogui.keyUp(key_lower)
                return ToolResult(output=f"Key up: {key}")

            elif action == "get_mouse_position":
                x, y = pyautogui.position()
                return ToolResult(output=f"Mouse position: ({x}, {y})")

            else:
                return ToolResult(output="", error=f"Unknown action: {action}")

        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    def _press_with_modifiers(self, key: str, modifiers: list[str]) -> None:
        """Press a key with modifier keys (Ctrl, Shift, Alt, Win)."""
        for mod in modifiers:
            pyautogui.keyDown(mod.lower())
        try:
            pyautogui.press(key)
        finally:
            for mod in reversed(modifiers):
                pyautogui.keyUp(mod.lower())


class ScreenshotWithOCRTool(BaseTool):
    """Take screenshot with optional OCR text extraction."""

    name: str = "screenshot_ocr"
    description: str = (
        "Take a screenshot and optionally extract text using OCR. "
        "Returns base64-encoded image and extracted text."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "region": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Top-left X"},
                    "y": {"type": "integer", "description": "Top-left Y"},
                    "width": {"type": "integer", "description": "Width"},
                    "height": {"type": "integer", "description": "Height"},
                },
                "description": "Optional region to capture (default: full screen)",
            },
            "extract_text": {
                "type": "boolean",
                "description": "Extract text using OCR (default: false)",
            },
            "highlight_text": {
                "type": "boolean",
                "description": "Draw rectangles around detected text (default: false)",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        region: Optional[dict] = None,
        extract_text: bool = False,
        highlight_text: bool = False,
        **_,
    ) -> ToolResult:
        """Take screenshot with optional OCR."""
        try:
            # Take screenshot
            if region:
                x = region.get("x", 0)
                y = region.get("y", 0)
                width = region.get("width", 100)
                height = region.get("height", 100)
                screenshot = pyautogui.screenshot(region=(x, y, x + width, y + height))
            else:
                screenshot = pyautogui.screenshot()

            # Encode to base64
            img_bytes = BytesIO()
            screenshot.save(img_bytes, format="PNG")
            img_base64 = base64.b64encode(img_bytes.getvalue()).decode("utf-8")

            # Extract text if requested
            text_output = ""
            if extract_text:
                try:
                    import pytesseract
                    text_output = pytesseract.image_to_string(screenshot)
                except ImportError:
                    text_output = "[OCR not available - install pytesseract]"
                except Exception as exc:
                    text_output = f"[OCR error: {exc}]"

            # Create annotated image if requested
            if highlight_text and extract_text:
                try:
                    import pytesseract
                    details = pytesseract.image_to_data(screenshot, output_type="dict")
                    img_copy = screenshot.copy()
                    draw = ImageDraw.Draw(img_copy)

                    for i, text in enumerate(details.get("text", [])):
                        if text.strip():
                            x = details["left"][i]
                            y = details["top"][i]
                            w = details["width"][i]
                            h = details["height"][i]
                            draw.rectangle([(x, y), (x + w, y + h)], outline="red", width=2)

                    img_bytes = BytesIO()
                    img_copy.save(img_bytes, format="PNG")
                    img_base64 = base64.b64encode(img_bytes.getvalue()).decode("utf-8")
                except Exception:
                    pass  # Fallback to original image

            output = f"Screenshot captured: {screenshot.size[0]}x{screenshot.size[1]} pixels"
            if text_output:
                output += f"\n\nExtracted text:\n{text_output}"

            return ToolResult(output=output, base64_image=img_base64)

        except Exception as exc:
            return ToolResult(output="", error=str(exc))


class ElementDetectorTool(BaseTool):
    """Detect clickable elements (buttons, links, text fields) on screen."""

    name: str = "detect_elements"
    description: str = (
        "Detect clickable elements on screen using OCR and image analysis. "
        "Returns list of detected elements with positions."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "element_type": {
                "type": "string",
                "enum": ["button", "link", "textfield", "image", "all"],
                "description": "Type of element to detect (default: all)",
            },
            "screenshot": {
                "type": "boolean",
                "description": "Return annotated screenshot with detected elements (default: true)",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        element_type: str = "all",
        screenshot: bool = True,
        **_,
    ) -> ToolResult:
        """Detect clickable elements on screen."""
        try:
            import pytesseract

            # Take screenshot
            img = pyautogui.screenshot()
            width, height = img.size

            # Use OCR to find text elements
            details = pytesseract.image_to_data(img, output_type="dict")

            elements = []
            for i, text in enumerate(details.get("text", [])):
                if not text.strip():
                    continue

                confidence = int(details.get("conf", [0])[i])
                if confidence < 50:
                    continue

                x = details["left"][i]
                y = details["top"][i]
                w = details["width"][i]
                h = details["height"][i]

                # Heuristic: likely clickable if it looks like button text
                is_button = any(
                    word in text.lower()
                    for word in ["button", "click", "submit", "ok", "cancel", "close", "save"]
                )

                element_info = {
                    "type": "button" if is_button else "text",
                    "text": text,
                    "position": {"x": x + w // 2, "y": y + h // 2},  # Center of element
                    "bounds": {"x": x, "y": y, "width": w, "height": h},
                    "confidence": confidence,
                }
                elements.append(element_info)

            # Create annotated screenshot
            img_annotated = img.copy()
            draw = ImageDraw.Draw(img_annotated)

            for elem in elements:
                bounds = elem["bounds"]
                x, y, w, h = bounds["x"], bounds["y"], bounds["width"], bounds["height"]
                color = "green" if elem["type"] == "button" else "blue"
                draw.rectangle([(x, y), (x + w, y + h)], outline=color, width=2)

            img_bytes = BytesIO()
            img_annotated.save(img_bytes, format="PNG")
            img_base64 = base64.b64encode(img_bytes.getvalue()).decode("utf-8")

            output = f"Detected {len(elements)} elements:\n\n"
            for i, elem in enumerate(elements[:10], 1):
                output += f"{i}. {elem['type'].upper()}: '{elem['text']}' at {elem['position']}\n"

            if len(elements) > 10:
                output += f"\n... and {len(elements) - 10} more elements"

            return ToolResult(output=output, base64_image=img_base64)

        except ImportError:
            return ToolResult(output="", error="pytesseract not available")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))
