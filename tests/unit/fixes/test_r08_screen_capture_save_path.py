"""R08 (audit 2026-10-29): screen_capture's save_path goes through the write rule.

``capture(save_path=...)`` opened any path for writing, so a model could overwrite a
document or ``.env`` with PNG bytes. The first version of this test proved it on the real
machine: it overwrote the developer's ``.env``. So the screen grab and the module's ``open``
are replaced here, and no path is ever really written, whether the check exists or not.
"""

from __future__ import annotations

import pytest

from weebot.core.output_path import _PROJECT_ROOT
from weebot.tools import screen_tool


class _Shot:
    size = (1, 1)
    rgb = b"\x00\x00\x00"


class _FakeMss:
    monitors = [{"width": 1, "height": 1, "left": 0, "top": 0}]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, _monitor):
        return _Shot()


@pytest.fixture
def opened(monkeypatch):
    calls: list[str] = []

    def _no_write(path, *args, **kwargs):
        calls.append(str(path))
        raise AssertionError(f"capture tried to write {path}")

    monkeypatch.setattr(screen_tool, "_MSS_AVAILABLE", True)
    monkeypatch.setattr(screen_tool, "_PIL_AVAILABLE", False)
    monkeypatch.setattr(screen_tool, "mss", _FakeMss)
    monkeypatch.setattr(screen_tool._mss_tools, "to_png", lambda rgb, size: b"png", raising=False)
    monkeypatch.setattr(screen_tool, "open", _no_write, raising=False)
    return calls


@pytest.mark.parametrize(
    "save_path",
    [
        "Output/r08_probe/notes.docx",  # not a PNG
        ".env",  # protected
        "weebot/config/settings.py",  # source
    ],
)
def test_a_bad_save_path_is_refused_and_nothing_is_written(opened, save_path):
    result = screen_tool.ScreenCaptureTool().capture(save_path=save_path)
    assert result["success"] is False
    assert opened == [], "the path reached open() unchecked"


def test_a_path_outside_the_project_is_refused(opened, tmp_path):
    result = screen_tool.ScreenCaptureTool().capture(save_path=str(tmp_path / "shot.png"))
    assert result["success"] is False and opened == []


def test_a_png_inside_the_project_is_written_there(opened):
    result = screen_tool.ScreenCaptureTool().capture(save_path="Output/r08_probe/shot.png")
    expected = str((_PROJECT_ROOT / "Output" / "r08_probe" / "shot.png").resolve())
    assert opened == [expected]  # the fake open refuses, so nothing lands on disk
    assert result["success"] is False
