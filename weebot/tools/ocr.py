"""OCR and text extraction tools."""
from __future__ import annotations

import base64
from io import BytesIO
from typing import Optional

from PIL import Image

from weebot.tools.base import BaseTool, ToolResult


class OCRTool(BaseTool):
    """Extract text from images using Tesseract OCR."""

    name: str = "ocr"
    description: str = (
        "Extract text from an image using OCR. "
        "Accepts base64-encoded PNG/JPEG images."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "image_base64": {
                "type": "string",
                "description": "Base64-encoded image (PNG or JPEG)",
            },
            "language": {
                "type": "string",
                "description": "Language code for OCR (e.g., 'eng', 'ell' for Greek, default: 'eng')",
            },
            "config": {
                "type": "string",
                "description": "Tesseract config (e.g., '--psm 6' for blocks, default: '')",
            },
        },
        "required": ["image_base64"],
    }

    async def execute(
        self,
        image_base64: str,
        language: str = "eng",
        config: str = "",
        **_,
    ) -> ToolResult:
        """Extract text from image using OCR."""
        try:
            import pytesseract

            # Decode image
            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))

            # Run OCR
            text = pytesseract.image_to_string(image, lang=language, config=config)

            if not text.strip():
                return ToolResult(
                    output="No text detected in image",
                )

            return ToolResult(output=f"Extracted text:\n\n{text}")

        except ImportError:
            return ToolResult(output="", error="pytesseract not installed")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))


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
            "image_base64": {
                "type": "string",
                "description": "Base64-encoded image (PNG or JPEG)",
            },
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
        self,
        image_base64: str,
        language: str = "eng",
        min_confidence: int = 50,
        **_,
    ) -> ToolResult:
        """Extract structured text with positions."""
        try:
            import pytesseract

            # Decode image
            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))

            # Run OCR with data
            details = pytesseract.image_to_data(image, lang=language, output_type="dict")

            # Build structured output
            text_items = []
            for i, text in enumerate(details.get("text", [])):
                if not text.strip():
                    continue

                confidence = int(details.get("conf", [0])[i])
                if confidence < min_confidence:
                    continue

                item = {
                    "text": text,
                    "confidence": confidence,
                    "position": {
                        "x": details["left"][i],
                        "y": details["top"][i],
                        "width": details["width"][i],
                        "height": details["height"][i],
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
