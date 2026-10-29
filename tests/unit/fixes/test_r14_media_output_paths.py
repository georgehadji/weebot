"""R14 (audit 2026-10-29): media tools write only media files, never protected ones.

image_gen and video_gen checked only that output_path was under the cwd, so
``output_path=".env"`` replaced the secrets file and ``.git/hooks/pre-commit`` or a ``.py``
file worked the same way. ``write_target`` (weebot/core/output_path.py) is the one rule for
a model-chosen write path: inside the project, not a protected name or executable type, and
of a type the tool produces.

The tool-level probes use a missing path under Output/, never the real .env.
"""

from __future__ import annotations

import pytest

from weebot.core.output_path import _PROJECT_ROOT, write_target

IMAGES = frozenset({".png", ".svg"})
PROBE = _PROJECT_ROOT / "Output" / "r14_probe"


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".git/hooks/pre-commit",
        "weebot/config/settings.py",  # source, not an image
        "Output/run.ps1",  # executable
        str(_PROJECT_ROOT.parent / "elsewhere.png"),  # outside the project
        "../elsewhere.png",
    ],
)
def test_protected_foreign_and_outside_paths_are_refused(path):
    with pytest.raises(ValueError):
        write_target(path, suffixes=IMAGES)


def test_a_media_path_inside_the_project_is_allowed():
    target = write_target("Output/images/hero.png", suffixes=IMAGES)
    assert target == str((_PROJECT_ROOT / "Output" / "images" / "hero.png").resolve())


def test_without_suffixes_executables_and_protected_names_are_still_refused():
    with pytest.raises(ValueError):
        write_target("Output/x.bat")
    with pytest.raises(ValueError):
        write_target("config/id_rsa")
    assert write_target("Output/export.jsonl").endswith("export.jsonl")


@pytest.mark.asyncio
async def test_image_gen_refuses_a_source_file(tmp_path):
    from weebot.tools.image_gen_tool import ImageGenTool

    target = PROBE / "not_an_image.py"
    result = await ImageGenTool().execute(kind="hero", output_path=str(target))
    assert result.error and not target.exists()


@pytest.mark.asyncio
async def test_video_gen_refuses_a_source_file(monkeypatch):
    from weebot.tools.video_gen_tool import VideoGenTool

    async def _never(self, params):
        raise AssertionError("the request was sent before the path was checked")

    monkeypatch.setattr(VideoGenTool, "_execute_openrouter", _never)
    target = PROBE / "not_a_video.py"
    result = await VideoGenTool().execute(prompt="a cat", output_path=str(target))
    assert result.error and not target.exists()


@pytest.mark.parametrize("path", [".env", "weebot/config/settings.py", "Output/run.cmd"])
def test_youtube_download_refuses_non_media_paths(path):
    from weebot.tools.youtube_download_tool import YouTubeDownloadTool

    with pytest.raises(ValueError):
        YouTubeDownloadTool._sanitize_output_path(path)
