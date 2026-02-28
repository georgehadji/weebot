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
                if monitor_index >= len(monitors):
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
