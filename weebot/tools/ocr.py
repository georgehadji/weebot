"""OCR and text extraction tools."""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import Field

from weebot.tools.base import BaseTool, ToolResult


def _read_refusal(image_path: str) -> str | None:
    """Why *image_path* may not be read, or None. Same rule as file_editor:
    inside the workspace, and allowed by the filesystem policy (F65)."""
    from weebot.config.fs_permissions import load_fs_permission_checker
    from weebot.config.settings import WORKSPACE_ROOT

    path = Path(image_path).resolve()
    if not path.is_relative_to(Path(WORKSPACE_ROOT).resolve()):
        return f"Access denied: {path} is outside the workspace {WORKSPACE_ROOT}"
    perm = load_fs_permission_checker()
    if perm.has_rules and perm.check("read", str(path)) != "allow":
        return f"Access denied: read on {path} is denied by filesystem policy"
    return None

logger = logging.getLogger(__name__)


class OCRTool(BaseTool):
    """Extract text from images using Tesseract OCR."""

    name: str = "ocr"
    description: str = (
        "Extract text from an image using OCR. Pass image_path (a PNG/JPEG file) or "
        "image_base64. Uses Tesseract, or the vision model when Tesseract is not installed."
    )
    # An LLMPort for a vision model, injected by DI (Container.tool_wiring).
    vision_llm: Any = Field(default=None, exclude=True)
    parameters: dict = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Path to a PNG or JPEG image file"},
            "image_base64": {"type": "string", "description": "Base64-encoded image (PNG or JPEG)"},
            "language": {
                "type": "string",
                "description": "Language code for OCR (e.g., 'eng', 'ell' for Greek, default: 'eng')",
            },
            "config": {
                "type": "string",
                "description": "Tesseract config (e.g., '--psm 6' for blocks, default: '')",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        image_base64: str | None = None,
        image_path: str | None = None,
        language: str = "eng",
        config: str = "",
        **_,
    ) -> ToolResult:
        """Extract text from image using OCR."""
        import asyncio

        try:
            if image_path:
                if refusal := _read_refusal(image_path):
                    return ToolResult(output="", error=refusal)
                image_data = await asyncio.to_thread(Path(image_path).read_bytes)
            elif image_base64:
                image_data = base64.b64decode(image_base64)
            else:
                return ToolResult(output="", error="Pass image_path or image_base64")
        except (OSError, ValueError) as exc:
            return ToolResult(output="", error=f"Cannot read image: {exc}")

        try:
            import pytesseract

            image = await asyncio.to_thread(lambda: Image.open(BytesIO(image_data)))
            text = await asyncio.to_thread(
                pytesseract.image_to_string, image, lang=language, config=config
            )
        except ImportError:
            return await self._vision_ocr(image_data, "pytesseract not installed")
        except Exception as exc:
            if type(exc).__name__ == "TesseractNotFoundError":
                return await self._vision_ocr(image_data, "Tesseract binary not installed")
            return ToolResult(output="", error=str(exc))

        if not text.strip():
            return ToolResult(output="No text detected in image")
        return ToolResult(output=f"Extracted text:\n\n{text}")

    async def _vision_ocr(self, image_data: bytes, why: str) -> ToolResult:
        """Read the text with the vision model when Tesseract cannot run."""
        if self.vision_llm is None:
            return ToolResult(output="", error=f"{why}, and no vision model is configured")
        from weebot.config.model_refs import MODEL_VISION_PRIMARY

        fmt = "jpeg" if image_data[:2] == b"\xff\xd8" else "png"  # magic bytes, no decode
        url = f"data:image/{fmt};base64,{base64.b64encode(image_data).decode()}"
        try:
            resp = await self.vision_llm.chat(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcribe all text in this image "
                             "exactly. Reply with the text only."},
                            {"type": "image_url", "image_url": {"url": url}},
                        ],
                    }
                ],
                model=MODEL_VISION_PRIMARY,
                max_tokens=1024,
            )
        except Exception as exc:
            logger.warning("Vision OCR failed: %s", exc)
            return ToolResult(output="", error=f"{why}; vision OCR failed: {exc}")
        text = (resp.content or "").strip()
        if not text:
            return ToolResult(output="No text detected in image")
        return ToolResult(output=f"Extracted text (vision model, {why}):\n\n{text}")


class StructuredOCRTool(BaseTool):
    """Extract structured text with position information from images."""

    name: str = "ocr_structured"
    description: str = (
        "Extract structured text with position and confidence info from image. "
        "Useful for understanding layout and locating text elements."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "image_base64": {"type": "string", "description": "Base64-encoded image (PNG or JPEG)"},
            "language": {
                "type": "string",
                "description": "Language code for OCR (e.g., 'eng', 'ell', default: 'eng')",
            },
            "min_confidence": {
                "type": "integer",
                "description": "Minimum confidence threshold (0-100, default: 50)",
            },
        },
        "required": ["image_base64"],
    }

    async def execute(
        self, image_base64: str, language: str = "eng", min_confidence: int = 50, **_
    ) -> ToolResult:
        """Extract structured text with positions."""
        try:
            import pytesseract
            import asyncio

            # Decode image (CPU-bound PIL in thread)
            image_data = base64.b64decode(image_base64)
            image = await asyncio.to_thread(lambda: Image.open(BytesIO(image_data)))

            # Run OCR with data (CPU-bound, run in thread)
            details = await asyncio.to_thread(
                pytesseract.image_to_data, image, lang=language, output_type="dict"
            )

            # Build structured output
            text_items = []
            conf_list = details.get("conf", [])
            left_list = details.get("left", [])
            top_list = details.get("top", [])
            width_list = details.get("width", [])
            height_list = details.get("height", [])

            for i, text in enumerate(details.get("text", [])):
                if not text.strip():
                    continue

                # Guard against mismatched list lengths from OCR
                if i >= len(conf_list):
                    continue
                confidence = int(conf_list[i])
                if confidence < min_confidence:
                    continue

                # Guard against mismatched position data
                if (
                    i >= len(left_list)
                    or i >= len(top_list)
                    or i >= len(width_list)
                    or i >= len(height_list)
                ):
                    continue

                item = {
                    "text": text,
                    "confidence": confidence,
                    "position": {
                        "x": left_list[i],
                        "y": top_list[i],
                        "width": width_list[i],
                        "height": height_list[i],
                    },
                }
                text_items.append(item)

            if not text_items:
                return ToolResult(output="No text detected above confidence threshold")

            # Format output
            output = f"Found {len(text_items)} text items:\n\n"
            for i, item in enumerate(text_items[:20], 1):
                output += (
                    f"{i}. '{item['text']}' "
                    f"(conf: {item['confidence']}%, pos: {item['position']['x']},{item['position']['y']})\n"
                )

            if len(text_items) > 20:
                output += f"\n... and {len(text_items) - 20} more items"

            return ToolResult(output=output)

        except ImportError:
            return ToolResult(output="", error="pytesseract not installed")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))
