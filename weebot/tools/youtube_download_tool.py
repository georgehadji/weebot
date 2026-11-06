"""Video download tool for weebot agents.

Downloads a video, or extracts its audio as MP3, from YouTube, Twitter/X,
TikTok, Instagram, Threads and 1800+ other sites by running the Yoinks CLI
(``node <yoinks>/dist/cli.js --best|--mp3 -o <dir> <url>``). Yoinks fetches and
updates its own yt-dlp and finds ffmpeg, so neither has to be on PATH.

Yoinks lives next to this project (``../Yoinks``); ``YOINKS_DIR`` points elsewhere.

Security: path traversal guard (write_target), http(s) validation, size cap, timeout.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field, PrivateAttr

from weebot.config.tool_config import ToolConfig, resolve_setting
from weebot.domain.models.output_trust import OutputTrust
from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Yoinks (through yt-dlp) decides whether it can handle the site.
_HTTP_URL_RE = re.compile(r"^https?://")

# ── Safety limits ──────────────────────────────────────────────────────
_MAX_VIDEO_SIZE_MB: int = 500  # 500 MiB ceiling, checked after the download
_DOWNLOAD_TIMEOUT_SEC: int = 300  # 5 min max download time
# What output_path may name (R14): a media file inside the project, never .env or source.
_MEDIA_SUFFIXES: frozenset[str] = frozenset(
    {".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".opus", ".wav"}
)
# The project root is two levels above weebot/tools/; Yoinks is cloned beside it.
_DEFAULT_YOINKS_DIR = Path(__file__).resolve().parents[2].parent / "Yoinks"


class YouTubeDownloadParams(BaseModel):
    """Parameters for a video download. Unknown keys (quality, cookies, ...) are ignored."""

    url: str = Field(description="Video page URL (http or https)")
    output_path: str = Field(
        default="", description="Output file path. If empty, auto-generated in Output/videos/"
    )
    format: str = Field(default="mp4", description="'mp4' (best video) or 'mp3' (audio only)")


class YouTubeDownloadTool(BaseTool):
    """Download a video, or its audio as MP3, by running the Yoinks CLI.

    Yoinks saves the best available quality; there is no resolution, container,
    cookie or JavaScript-runtime option. A video it cannot fetch (private,
    age-restricted, geo-blocked) fails with Yoinks's own message.

    Usage:
        youtube_download(url="https://youtube.com/watch?v=dQw4w9WgXcQ",
                         output_path="Output/videos/clip.mp4")
        youtube_download(url="https://youtu.be/dQw4w9WgXcQ", format="mp3")
    """

    output_trust: ClassVar[OutputTrust] = OutputTrust.EXTERNAL

    default_timeout_seconds: int = _DOWNLOAD_TIMEOUT_SEC
    name: str = "youtube_download"
    description: str = (
        "Download a video or extract MP3 audio from YouTube, Twitter/X, TikTok, "
        "Instagram, Threads and 1800+ other sites, using the Yoinks downloader. "
        "Parameters: url (required, http or https), output_path (optional, "
        "auto-generated under Output/videos/ if empty), format ('mp4' = best video, "
        "'mp3' = audio only). Quality is always the best available; there are no "
        "resolution, container, cookie or JS-runtime options. "
        "A single video only, never a playlist. After download, the file path is returned.\n\n"
        "If the download fails: use video_ingest to fetch the transcript/subtitles, "
        "or web_search to find the same video on another platform."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Video page URL (http or https)"},
            "output_path": {
                "type": "string",
                "description": "Output file path (auto-generated if empty)",
            },
            "format": {
                "type": "string",
                "enum": ["mp4", "mp3"],
                "description": "mp4 = best video (default), mp3 = audio only",
            },
        },
        "required": ["url"],
    }

    _tool_config: ToolConfig | None = PrivateAttr(default=None)

    def set_config(self, config: ToolConfig) -> None:
        self._tool_config = config

    # ── Public API ──────────────────────────────────────────────────────

    async def execute(self, url: str, **kwargs: Any) -> ToolResult:
        params = YouTubeDownloadParams(
            url=url, **{k: v for k, v in kwargs.items() if v is not None}
        )

        if not _HTTP_URL_RE.match(params.url):
            return ToolResult.error_result(
                f"Invalid URL: {params.url[:80]}. Expected an http(s):// URL to a video page."
            )

        node = shutil.which("node")
        if node is None:
            return ToolResult.error_result(
                "Node.js (22 or newer) is not on PATH, and Yoinks needs it to run."
            )
        cli = self._cli_path()
        if not cli.is_file():
            return ToolResult.error_result(
                f"Yoinks is not built at {cli}. Run `npm install && npm run build` in "
                f"{cli.parent.parent}, or set YOINKS_DIR to the Yoinks folder."
            )

        audio = params.format in ("mp3", "audio")
        output_path = params.output_path
        if not output_path:
            import uuid

            ext = "mp3" if audio else "mp4"
            output_path = f"Output/videos/youtube_{uuid.uuid4().hex[:8]}.{ext}"
        try:
            path = self._sanitize_output_path(output_path)
        except ValueError as exc:
            return ToolResult.error_result(f"output_path refused: {exc}")
        path.parent.mkdir(parents=True, exist_ok=True)

        saved, error = await self._run_yoinks(node, cli, params.url, path.parent, audio)
        if saved is None:
            return ToolResult.error_result(
                f"Video download failed for {params.url[:60]}. {error}\n\n"
                "Try the next approach in the same step: video_ingest for the "
                "transcript/subtitles, or web_search for the video on another site."
            )

        size = saved.stat().st_size
        if size > _MAX_VIDEO_SIZE_MB * 1024 * 1024:
            saved.unlink(missing_ok=True)
            return ToolResult.error_result(
                f"The video is {size // (1024 * 1024)} MiB, over the {_MAX_VIDEO_SIZE_MB} MiB "
                "limit. It was deleted; pick a shorter video."
            )

        final = self._move_to_requested(saved, path)
        logger.info("Video download complete: %s (%d bytes)", final, size)
        return ToolResult(
            output=f"Downloaded video: {final} ({size} bytes)",
            data={
                "path": str(final.resolve()),
                "size_bytes": size,
                "format": "mp3" if audio else "mp4",
                "url": params.url[:80],
            },
        )

    # ── Yoinks ──────────────────────────────────────────────────────────

    def _cli_path(self) -> Path:
        """``<yoinks>/dist/cli.js``: YOINKS_DIR, else the Yoinks folder beside this project."""
        configured = resolve_setting(self._tool_config, "yoinks_dir", "YOINKS_DIR")
        root = Path(configured) if configured else _DEFAULT_YOINKS_DIR
        return root / "dist" / "cli.js"

    @staticmethod
    async def _run_yoinks(
        node: str, cli: Path, url: str, out_dir: Path, audio: bool
    ) -> tuple[Path | None, str]:
        """Run Yoinks' scriptable mode; return (saved file, "") or (None, reason).

        It prints one saved path per line on stdout; status and errors go to stderr.
        """
        cmd = [node, str(cli), "--mp3" if audio else "--best", "-o", str(out_dir), url]
        logger.info("Downloading video: %s", url[:60])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except OSError as exc:
            logger.warning("Could not start Yoinks: %s", exc)
            return None, f"Could not start Yoinks: {exc}"
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_DOWNLOAD_TIMEOUT_SEC
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("Video download timed out after %ds", _DOWNLOAD_TIMEOUT_SEC)
            return None, f"Timed out after {_DOWNLOAD_TIMEOUT_SEC}s."

        if proc.returncode != 0:
            detail = stderr.decode(errors="replace").strip()[-500:]
            logger.warning("Yoinks failed (exit %s): %s", proc.returncode, detail)
            return None, detail or f"Yoinks exited with code {proc.returncode}."
        for line in stdout.decode(errors="replace").splitlines():
            saved = Path(line.strip())
            if line.strip() and saved.is_file():
                return saved, ""
        logger.warning("Yoinks reported success but printed no existing file: %r", stdout[:200])
        return None, "Yoinks finished but did not report a saved file."

    @staticmethod
    def _move_to_requested(saved: Path, requested: Path) -> Path:
        """Give the file the requested name (keeping its real extension); never overwrite."""
        target = requested.with_suffix(saved.suffix) if saved.suffix else requested
        if target == saved or target.exists() or saved.suffix.lower() not in _MEDIA_SUFFIXES:
            return saved
        try:
            return saved.replace(target)
        except OSError as exc:
            logger.warning("Could not move %s to %s: %s", saved, target, exc)
            return saved

    @staticmethod
    def _sanitize_output_path(output_path: str) -> Path:
        """The absolute path *output_path* may be written to (``write_target``, R14)."""
        from weebot.core.output_path import write_target

        return Path(write_target(output_path, suffixes=_MEDIA_SUFFIXES))

    async def health_check(self) -> bool:
        """Node must be on PATH and Yoinks built."""
        return shutil.which("node") is not None and self._cli_path().is_file()
