"""Regression tests for Phase 1 safety fixes in ImageGenTool.

Covers:
- F2: Path traversal guard (_sanitize_output_path)
- F3: HTTPS guard + streaming download (_download_image)
- F5: SVG & escaping
"""
from __future__ import annotations

import asyncio
import pytest


# ══════════════════════════════════════════════════════════════════════
# F2: Path traversal guard
# ══════════════════════════════════════════════════════════════════════

def test_sanitize_output_path_rejects_dotdot():
    """_sanitize_output_path must reject paths containing '..'."""
    from weebot.tools.image_gen_tool import ImageGenTool
    t = ImageGenTool()
    with pytest.raises(ValueError, match="Unsafe|escapes"):
        t._sanitize_output_path("../../etc/bad.png")


def test_sanitize_output_path_accepts_safe():
    """_sanitize_output_path must accept paths within the workspace."""
    from weebot.tools.image_gen_tool import ImageGenTool, _SAFE_BASE
    t = ImageGenTool()
    safe = str(_SAFE_BASE / "Output" / "images" / "test.png")
    result = t._sanitize_output_path(safe)
    assert result == _SAFE_BASE / "Output" / "images" / "test.png"


# ══════════════════════════════════════════════════════════════════════
# F3: HTTPS guard + streaming download
# ══════════════════════════════════════════════════════════════════════

def test_download_image_rejects_http():
    """_download_image must return None for http:// URLs."""
    from weebot.tools.image_gen_tool import ImageGenTool
    import asyncio
    t = ImageGenTool()
    result = asyncio.run(
        t._download_image(
            image_url="http://example.com/img.png",
            output_path="/tmp/_test_http.png",
            model="test",
            prompt="test",
        )
    )
    assert result is None, f"Expected None for http:// URL, got {result!r}"


def test_max_image_bytes_constant():
    """_MAX_IMAGE_BYTES must be a positive integer."""
    from weebot.tools.image_gen_tool import _MAX_IMAGE_BYTES
    assert isinstance(_MAX_IMAGE_BYTES, int)
    assert _MAX_IMAGE_BYTES > 0


# ══════════════════════════════════════════════════════════════════════
# F5: SVG & escaping
# ══════════════════════════════════════════════════════════════════════

def test_svg_sanitize_strips_ampersand():
    """_sanitize must strip & from user text."""
    from weebot.tools.image_gen_tool import ImageGenTool
    result = ImageGenTool._sanitize("Research & Development")
    assert "&" not in result, f"ampersand not stripped: {result!r}"


def test_svg_sanitize_strips_all_specials():
    """_sanitize must strip all XML-special characters: < > \" ' &."""
    from weebot.tools.image_gen_tool import ImageGenTool
    result = ImageGenTool._sanitize('a<b>c"d\'e&f')
    for char in '<>"\'&':
        assert char not in result, f"{char!r} not stripped from {result!r}"
