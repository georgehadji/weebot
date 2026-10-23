"""image_gen writes only inside the workspace, on every branch (F50).

The workspace check ran only in `_download_image`; the SVG kinds, the SVG
fallback and xAI base64 images wrote `output_path` wherever it pointed.
"""

from __future__ import annotations

from weebot.tools.image_gen_tool import ImageGenTool


async def test_an_svg_kind_outside_the_workspace_is_refused(tmp_path):
    target = tmp_path / "outside.svg"  # pytest's tmp dir is outside the repo
    result = await ImageGenTool().execute(kind="hero", output_path=str(target), title="t")
    assert result.is_error and "workspace" in (result.error or "")
    assert not target.exists()


async def test_voice_output_outside_the_workspace_is_refused(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from weebot.tools.voice_output_tool import VoiceOutputTool

    speech = MagicMock()
    speech.synthesize = AsyncMock(return_value=b"RIFF")
    target = tmp_path / "x.wav"
    result = await VoiceOutputTool(speech=speech).execute(text="hi", output_path=str(target))
    assert result.is_error and not target.exists()


async def test_video_ingest_export_outside_the_workspace_is_refused(tmp_path):
    from unittest.mock import MagicMock

    from weebot.tools.video_ingest_tool import VideoIngestTool

    target = tmp_path / "out.jsonl"
    tool = VideoIngestTool(repo=MagicMock())
    result = await tool._export_jsonl({"project_id": "p", "output_path": str(target)})
    assert result.is_error and "escapes" in (result.error or "") and not target.exists()
