"""Screen capture tool using mss."""
import io
from typing import Any, Dict, List, Optional

try:
    from mss import mss
    import mss.tools
    _MSS_AVAILABLE = True
except ImportError:
    _MSS_AVAILABLE = False
    mss = None

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    Image = None


class ScreenCaptureTool:
    """Capture screenshots of any connected monitor."""

    def list_screens(self) -> List[Dict[str, Any]]:
        """Return metadata for each connected monitor."""
        if not _MSS_AVAILABLE:
            return []
        with mss() as sct:
            return [
                {"index": i, "width": m["width"], "height": m["height"],
                 "left": m["left"], "top": m["top"]}
                for i, m in enumerate(sct.monitors)
            ]

    def capture(self, monitor_index: int = 0, save_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Capture a screenshot.

        Returns:
            {"success": bool, "output": str, "data": bytes | None}
            data is PNG bytes if success, None otherwise.
        """
        if not _MSS_AVAILABLE:
            return {"success": False, "output": "mss not installed", "data": None}

        try:
            with mss() as sct:
                monitors = sct.monitors
                if monitor_index < 0 or monitor_index >= len(monitors):
                    return {
                        "success": False,
                        "output": f"Invalid monitor index {monitor_index} (max {len(monitors)-1})",
                        "data": None,
                    }
                screenshot = sct.grab(monitors[monitor_index])

                # Convert to PNG bytes via Pillow if available, else mss.tools
                if _PIL_AVAILABLE:
                    img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    png_bytes = buf.getvalue()
                else:
                    import mss.tools as _mss_tools
                    png_bytes = _mss_tools.to_png(screenshot.rgb, screenshot.size)

                if save_path:
                    with open(save_path, "wb") as f:
                        f.write(png_bytes)

                return {
                    "success": True,
                    "output": f"Captured monitor {monitor_index} ({screenshot.width}x{screenshot.height})",
                    "data": png_bytes,
                }
        except Exception as e:
            return {"success": False, "output": f"Capture error: {e}", "data": None}


# --- weebot BaseTool wrapper -------------------------------------------------
import base64  # noqa: E402
from pydantic import ConfigDict, PrivateAttr  # noqa: E402
from weebot.tools.base import BaseTool as _WeebotBaseTool, ToolResult as _ToolResult  # noqa: E402


class ScreenCaptureBaseTool(_WeebotBaseTool):
    """weebot BaseTool wrapper around ScreenCaptureTool for use in the ReAct agent."""

    name: str = "screen_capture"
    description: str = (
        "Capture a screenshot of a connected monitor. "
        "Returns the image as base64-encoded PNG. "
        "Use monitor_index=0 for the primary monitor."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "monitor_index": {
                "type": "integer",
                "description": "Monitor to capture (0 = primary). Defaults to 0.",
                "default": 0,
            },
            "save_path": {
                "type": "string",
                "description": "Optional file path to also save the PNG file",
            },
        },
        "required": [],
    }

    model_config = ConfigDict(arbitrary_types_allowed=True)
    _inner: ScreenCaptureTool = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        self._inner = ScreenCaptureTool()

    async def execute(  # type: ignore[override]
        self,
        monitor_index: int = 0,
        save_path: str | None = None,
        **_,
    ) -> _ToolResult:
        result = self._inner.capture(monitor_index=monitor_index, save_path=save_path)
        if not result["success"]:
            return _ToolResult(output="", error=result["output"])
        png_bytes: bytes = result["data"]
        b64 = base64.b64encode(png_bytes).decode()
        return _ToolResult(output=result["output"], base64_image=b64)
