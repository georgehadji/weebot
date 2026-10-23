"""ocr reads images under the same rule as file_editor (F65).

It read any path it was given and, without pytesseract, sent the raw bytes to
the vision provider, while file_editor (same roles) is confined to the
workspace and the filesystem policy.
"""

from __future__ import annotations

from weebot.tools.ocr import OCRTool


async def test_a_path_outside_the_workspace_is_refused(tmp_path):
    secret = tmp_path / "id_rsa.png"  # pytest's tmp dir is outside the workspace
    secret.write_bytes(b"\x89PNG\r\n\x1a\nsecret")
    result = await OCRTool().execute(image_path=str(secret))
    assert result.is_error and "workspace" in (result.error or "").lower()
