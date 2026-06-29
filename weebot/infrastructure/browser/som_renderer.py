"""Set-of-Mark (SoM) visual overlay renderer for browser screenshots.

Based on the paper "Fundamentals of Building Autonomous LLM Agents"
(arXiv:2510.09244v1), §3.5: "The agent applies a Set-of-Mark operation
using a visual encoder that draws a box on every interactive element
and stores the coordinates of each box."

Usage:
    renderer = SomRenderer()
    annotated = await renderer.render(screenshot_bytes, elements, page_size)
    # annotated["image"] -> base64 PNG with numbered boxes
    # annotated["marks"] -> list of element -> number mappings
"""
from __future__ import annotations

import base64
import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Pillow is optional — needed for image overlay rendering
try:
    from PIL import Image, ImageDraw, ImageFont
    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False


class SomRenderer:
    """Renders numbered bounding-box overlays on browser screenshots.

    Each interactive element detected on the page gets a numbered box.
    The LLM can then reference element numbers in its actions
    (e.g., "click button #3") instead of guessing raw coordinates.
    """

    # SoM color scheme — high-contrast on most backgrounds
    _BOX_COLOR: tuple[int, int, int] = (255, 50, 50)       # Red border
    _FILL_COLOR: tuple[int, int, int, int] = (255, 50, 50, 40)  # Semi-transparent red
    _LABEL_BG: tuple[int, int, int] = (255, 50, 50)        # Red label background
    _LABEL_FG: tuple[int, int, int] = (255, 255, 255)      # White label text

    async def render(
        self,
        screenshot_bytes: bytes,
        elements: list[dict[str, Any]],
        page_width: int = 1920,
        page_height: int = 1080,
    ) -> dict[str, Any]:
        """Overlay numbered bounding boxes on a screenshot.

        Args:
            screenshot_bytes: Raw PNG screenshot bytes.
            elements: List of element dicts, each with a ``bounding_box``
                      key containing ``x``, ``y``, ``width``, ``height``.
            page_width: Viewport width for coordinate normalization.
            page_height: Viewport height for coordinate normalization.

        Returns:
            Dict with keys:
            - ``image``: base64-encoded PNG with overlays (or raw screenshot
              if Pillow unavailable).
            - ``marks``: list of ``{"number": int, "bbox": dict, "element": dict}``.
            - ``pillow_available``: whether Pillow was used for overlay.
        """
        # Filter elements that have valid bounding boxes
        valid_elements = []
        for el in elements:
            box = el.get("bounding_box") or el.get("bbox")
            if box and box.get("width", 0) > 5 and box.get("height", 0) > 5:
                valid_elements.append({"element": el, "bbox": box})

        # Limit to 50 marks — beyond that the overlay is too dense
        valid_elements = valid_elements[:50]

        marks = [
            {"number": i + 1, "bbox": ve["bbox"], "element": ve["element"]}
            for i, ve in enumerate(valid_elements)
        ]

        result: dict[str, Any] = {
            "marks": marks,
            "mark_count": len(marks),
            "pillow_available": _PILLOW_AVAILABLE,
        }

        if _PILLOW_AVAILABLE and screenshot_bytes:
            try:
                annotated = self._render_with_pillow(screenshot_bytes, marks)
                result["image"] = annotated
                result["overlay_rendered"] = True
            except Exception as exc:
                logger.warning("SoM Pillow rendering failed: %s", exc)
                result["image"] = base64.b64encode(screenshot_bytes).decode("utf-8")
                result["overlay_rendered"] = False
        elif screenshot_bytes:
            # Pillow not available — return raw screenshot + mark instructions
            result["image"] = base64.b64encode(screenshot_bytes).decode("utf-8")
            result["overlay_rendered"] = False

        return result

    @staticmethod
    def _render_with_pillow(
        screenshot_bytes: bytes,
        marks: list[dict[str, Any]],
    ) -> str:
        """Draw numbered bounding boxes on a screenshot using Pillow.

        Returns base64-encoded PNG.
        """
        import io as _io

        img = Image.open(_io.BytesIO(screenshot_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Try to load a font — fall back to default
        font = None
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except (OSError, IOError):
            try:
                font = ImageFont.load_default()
            except Exception:
                pass

        for mark in marks:
            box = mark["bbox"]
            number = mark["number"]

            x = int(box.get("x", 0))
            y = int(box.get("y", 0))
            w = int(box.get("width", 0))
            h = int(box.get("height", 0))

            if w <= 0 or h <= 0:
                continue

            # Draw filled bounding box (semi-transparent)
            draw.rectangle([x, y, x + w, y + h], fill=SomRenderer._FILL_COLOR)

            # Draw solid border
            draw.rectangle([x, y, x + w, y + h], outline=SomRenderer._BOX_COLOR, width=2)

            # Draw number label in top-left corner
            label_text = str(number)
            bbox = draw.textbbox((0, 0), label_text, font=font) if font else (0, 0, 14, 14)
            lw = bbox[2] - bbox[0] + 6
            lh = bbox[3] - bbox[1] + 4
            draw.rectangle([x, y - lh, x + lw, y], fill=SomRenderer._LABEL_BG)
            draw.text((x + 3, y - lh + 2), label_text, fill=SomRenderer._LABEL_FG, font=font)

        # Composite overlay onto original image
        result = Image.alpha_composite(img, overlay).convert("RGB")

        buf = _io.BytesIO()
        result.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")


class DesktopSomRenderer(SomRenderer):
    """Set-of-Mark renderer for desktop accessibility trees.

    Same numbered-box logic as SomRenderer but uses coordinates from
    DesktopA11yTool instead of browser DOM nodes. Works with OSWorld
    VM screenshots and native desktop windows.

    Key difference: bounds are absolute screen coordinates (x, y on the
    whole desktop), not relative to a browser viewport. The renderer
    clips boxes to the capture region when a region is specified.
    """

    async def render_desktop(
        self,
        screenshot_bytes: bytes,
        elements: list[dict[str, Any]],
        region: tuple[int, int, int, int] | None = None,
        max_marks: int = 50,
    ) -> str:
        """Render numbered overlays on a desktop screenshot.

        Args:
            screenshot_bytes: PNG bytes of the desktop screenshot.
            elements: List of element dicts with ``bounds`` sub-dict
                      (``x``, ``y``, ``w``, ``h``) and ``name``/``role``.
            region: Optional (x, y, w, h) capture region to clip to.
                    Elements outside this region are filtered out.
            max_marks: Maximum marks to draw (capped at 50).

        Returns:
            Base64-encoded PNG with numbered overlays.
        """
        if not _PILLOW_AVAILABLE:
            return base64.b64encode(screenshot_bytes).decode()

        # Filter elements with valid bounds, clip to region if specified
        valid = []
        for el in elements:
            bounds = el.get("bounds", {})
            if not all(k in bounds for k in ("x", "y", "w", "h")):
                continue
            ex, ey, ew, eh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
            if ew <= 0 or eh <= 0:
                continue
            if region:
                rx, ry, rw, rh = region
                # Clip: element must intersect the region
                if ex > rx + rw or ex + ew < rx or ey > ry + rh or ey + eh < ry:
                    continue
                # Offset to region-relative coordinates
                bounds = {"x": ex - rx, "y": ey - ry, "w": ew, "h": eh}
                el = {**el, "bounds": bounds}
            valid.append(el)

        # Create overlay from remaining elements
        img, overlay, draw, font = await self._prepare_base(screenshot_bytes, region)
        marked = 0
        for number, el in enumerate(valid[:max_marks], start=1):
            b = el["bounds"]
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            if w < 4 or h < 4:
                continue
            draw.rectangle([x, y, x + w, y + h], fill=self._FILL_COLOR)
            draw.rectangle([x, y, x + w, y + h], outline=self._BOX_COLOR, width=2)
            label_text = str(number)
            bbox = draw.textbbox((0, 0), label_text, font=font) if font else (0, 0, 14, 14)
            lw = bbox[2] - bbox[0] + 6
            lh = bbox[3] - bbox[1] + 4
            draw.rectangle([x, y - lh, x + lw, y], fill=self._LABEL_BG)
            draw.text((x + 3, y - lh + 2), label_text, fill=self._LABEL_FG, font=font)
            marked += 1

        result = Image.alpha_composite(img, overlay).convert("RGB")
        buf = _io.BytesIO()
        result.save(buf, format="PNG")
        logger.info("DesktopSoM: %d marks rendered", marked)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    async def _prepare_base(
        self,
        screenshot_bytes: bytes,
        region: tuple[int, int, int, int] | None = None,
    ):
        """Load image and prepare overlay canvas, clipped to region if given."""
        import io as _io2
        img = Image.open(_io2.BytesIO(screenshot_bytes)).convert("RGBA")
        if region:
            rx, ry, rw, rh = region
            img = img.crop((rx, ry, rx + rw, ry + rh))
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = None
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", 14)
            except Exception:
                pass
        return img, overlay, draw, font
