"""youtube_download runs the Yoinks CLI (``node <yoinks>/dist/cli.js --best|--mp3 -o <dir> <url>``).

No real node, network or Yoinks: a fake subprocess stands in and writes the file Yoinks would.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from weebot.config.tool_config import ToolConfig
from weebot.tools import youtube_download_tool as mod
from weebot.tools.youtube_download_tool import YouTubeDownloadTool

URL = "https://youtu.be/abc123"


class _Proc:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", code: int = 0, hang: bool = False):
        self._out, self._err, self.returncode, self._hang = stdout, stderr, code, hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(5)
        return self._out, self._err

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


class _Yoinks:
    """Records the command and, like Yoinks, saves ``<title><suffix>`` into the -o folder."""

    def __init__(self, title="Some Title", suffix=".mp4", code=0, stderr=b"", hang=False):
        self.calls: list[list[str]] = []
        self.title, self.suffix, self.code = title, suffix, code
        self.stderr, self.hang = stderr, hang
        self.proc: _Proc | None = None

    async def __call__(self, *cmd, **_kw):
        self.calls.append(list(cmd))
        out_dir = Path(cmd[cmd.index("-o") + 1])
        saved = out_dir / f"{self.title}{self.suffix}"
        if self.code == 0 and self.title:
            saved.write_bytes(b"x" * 10)
        stdout = f"{saved}\n".encode() if self.code == 0 and self.title else b""
        self.proc = _Proc(stdout, self.stderr, self.code, self.hang)
        return self.proc


@pytest.fixture
def yoinks_dir(tmp_path):
    root = tmp_path / "Yoinks"
    (root / "dist").mkdir(parents=True)
    (root / "dist" / "cli.js").write_text("// built", encoding="utf-8")
    return root


@pytest.fixture
def asked():
    """The output_path each call handed to the path guard."""
    return []


@pytest.fixture
def tool(yoinks_dir, tmp_path, monkeypatch, asked):
    """A tool pointed at the fake Yoinks, writing under tmp_path instead of the project."""
    monkeypatch.setattr(mod.shutil, "which", lambda name: "node")
    t = YouTubeDownloadTool()
    t.set_config(ToolConfig(yoinks_dir=str(yoinks_dir)))
    def sanitize(output_path: str) -> Path:
        asked.append(output_path)
        return tmp_path / "videos" / Path(output_path).name

    monkeypatch.setattr(YouTubeDownloadTool, "_sanitize_output_path", staticmethod(sanitize))
    return t


def _use(monkeypatch, fake: _Yoinks) -> _Yoinks:
    monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake)
    return fake


async def test_a_video_is_fetched_with_best_into_the_output_folder_and_named_as_asked(
    tool, monkeypatch, tmp_path, yoinks_dir
):
    fake = _use(monkeypatch, _Yoinks())

    result = await tool.execute(URL, output_path="Output/videos/clip.mp4")

    assert not result.error
    assert fake.calls == [
        ["node", str(yoinks_dir / "dist" / "cli.js"), "--best", "-o", str(tmp_path / "videos"), URL]
    ]
    target = tmp_path / "videos" / "clip.mp4"
    assert result.data["path"] == str(target.resolve()) and target.is_file()
    assert not (tmp_path / "videos" / "Some Title.mp4").exists()


@pytest.mark.parametrize("fmt", ["mp3", "audio"])
async def test_audio_formats_use_mp3_and_the_default_path_is_an_mp3(
    tool, asked, monkeypatch, fmt
):
    fake = _use(monkeypatch, _Yoinks(suffix=".mp3"))

    result = await tool.execute(URL, format=fmt)

    assert "--mp3" in fake.calls[0] and "--best" not in fake.calls[0]
    assert asked[0].startswith("Output/videos/youtube_") and asked[0].endswith(".mp3")
    assert result.data["format"] == "mp3" and result.data["path"].endswith(".mp3")


async def test_options_yoinks_does_not_have_are_ignored_not_fatal(tool, monkeypatch):
    fake = _use(monkeypatch, _Yoinks())

    result = await tool.execute(
        URL, quality="720p", cookies="c.txt", js_runtime="deno", format="webm"
    )

    assert not result.error
    assert "--best" in fake.calls[0] and "720p" not in fake.calls[0]


async def test_a_playlist_is_never_requested(tool, monkeypatch):
    fake = _use(monkeypatch, _Yoinks())

    await tool.execute(URL)

    assert "--playlist" not in fake.calls[0]


async def test_the_real_extension_is_kept_when_it_differs_from_the_requested_one(
    tool, monkeypatch, tmp_path
):
    _use(monkeypatch, _Yoinks(suffix=".mkv"))

    result = await tool.execute(URL, output_path="Output/videos/clip.mp4")

    assert result.data["path"] == str((tmp_path / "videos" / "clip.mkv").resolve())


async def test_an_existing_file_is_not_overwritten(tool, monkeypatch, tmp_path):
    (tmp_path / "videos").mkdir()
    keep = tmp_path / "videos" / "clip.mp4"
    keep.write_bytes(b"precious")
    _use(monkeypatch, _Yoinks())

    result = await tool.execute(URL, output_path="Output/videos/clip.mp4")

    assert keep.read_bytes() == b"precious"
    assert result.data["path"] == str((tmp_path / "videos" / "Some Title.mp4").resolve())


async def test_a_failed_download_reports_yoinks_message_and_the_fallbacks(tool, monkeypatch):
    _use(monkeypatch, _Yoinks(code=1, stderr=b"yoinks: Video unavailable\n"))

    result = await tool.execute(URL)

    assert "Video unavailable" in result.error
    assert "video_ingest" in result.error and "web_search" in result.error


async def test_success_with_no_reported_file_is_an_error(tool, monkeypatch):
    _use(monkeypatch, _Yoinks(title=""))

    result = await tool.execute(URL)

    assert "did not report a saved file" in result.error


async def test_a_hung_download_is_killed_after_the_timeout(tool, monkeypatch):
    monkeypatch.setattr(mod, "_DOWNLOAD_TIMEOUT_SEC", 0.05)
    fake = _use(monkeypatch, _Yoinks(hang=True))

    result = await tool.execute(URL)

    assert fake.proc.killed and "Timed out" in result.error


async def test_a_file_over_the_size_cap_is_deleted_and_refused(tool, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_MAX_VIDEO_SIZE_MB", 0)
    _use(monkeypatch, _Yoinks())

    result = await tool.execute(URL, output_path="Output/videos/big.mp4")

    assert "limit" in result.error
    assert list((tmp_path / "videos").glob("*")) == []


async def test_a_missing_yoinks_build_says_how_to_build_it(tool, yoinks_dir):
    (yoinks_dir / "dist" / "cli.js").unlink()

    result = await tool.execute(URL)

    assert "npm install && npm run build" in result.error and str(yoinks_dir) in result.error
    assert await tool.health_check() is False


async def test_missing_node_is_reported(tool, monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    result = await tool.execute(URL)

    assert "Node.js" in result.error and await tool.health_check() is False


async def test_a_non_http_url_is_refused_before_anything_runs(tool, monkeypatch):
    fake = _use(monkeypatch, _Yoinks())

    for bad in ("file:///etc/passwd", "--help", "javascript:alert(1)"):
        assert "Invalid URL" in (await tool.execute(bad)).error
    assert fake.calls == []


async def test_a_protected_output_path_becomes_an_error_result_not_a_crash(yoinks_dir, monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "node")
    t = YouTubeDownloadTool()
    t.set_config(ToolConfig(yoinks_dir=str(yoinks_dir)))
    fake = _use(monkeypatch, _Yoinks())

    result = await t.execute(URL, output_path=".env")

    assert "output_path refused" in result.error and fake.calls == []


def test_the_default_yoinks_folder_sits_beside_the_project(monkeypatch):
    monkeypatch.delenv("YOINKS_DIR", raising=False)
    project_root = Path(mod.__file__).resolve().parents[2]

    assert YouTubeDownloadTool()._cli_path() == project_root.parent / "Yoinks" / "dist" / "cli.js"


def test_yoinks_dir_from_the_environment_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv("YOINKS_DIR", str(tmp_path))

    assert YouTubeDownloadTool()._cli_path() == tmp_path / "dist" / "cli.js"
