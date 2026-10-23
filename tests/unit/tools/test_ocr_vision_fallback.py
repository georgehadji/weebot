"""OCR works without Tesseract: it falls back to the vision model.

Seen in the 2026-10-23 agent-uses batch: pytesseract is not in the venv and
the Tesseract binary is not installed, so `ocr` returned "pytesseract not
installed" and the agent spent the whole 6-minute budget trying to install
it. Vision models read text reliably (the vision eval read digits 4/4), so
`ocr` uses the injected vision LLM when Tesseract cannot run. It also takes
an image path, since agents hold files, not base64.
"""

from __future__ import annotations

import sys

import pytest
from PIL import Image

from weebot.domain.models.llm_response import LLMResponse
from weebot.tools.ocr import OCRTool


class _Vision:
    def __init__(self):
        self.messages = None

    async def chat(self, messages, **kw):
        self.messages = messages
        return LLMResponse(content="HELLO 42", tool_calls=None, usage=None)


@pytest.fixture
def no_tesseract(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", None)  # import raises ImportError


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "t.png"
    Image.new("RGB", (40, 20), "white").save(path)
    return path


@pytest.mark.asyncio
async def test_without_tesseract_the_vision_model_reads_the_image(no_tesseract, png):
    vision = _Vision()
    result = await OCRTool(vision_llm=vision).execute(image_path=str(png))
    assert result.error is None
    assert "HELLO 42" in result.output
    image_part = vision.messages[-1]["content"][-1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_without_tesseract_or_a_vision_model_it_says_so(no_tesseract, png):
    result = await OCRTool().execute(image_path=str(png))
    assert result.error and "tesseract" in result.error.lower()


@pytest.mark.asyncio
async def test_a_missing_image_path_is_an_error(tmp_path):
    result = await OCRTool(vision_llm=_Vision()).execute(image_path=str(tmp_path / "none.png"))
    assert result.error
