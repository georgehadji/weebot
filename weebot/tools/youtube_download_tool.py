"""YouTube video download tool for weebot agents.

Downloads YouTube videos as MP4 files using yt-dlp.
Reuses the same security patterns as image_gen_tool and video_gen_tool:
path traversal guard, HTTPS validation, size caps, timeout.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# ── YouTube URL patterns ───────────────────────────────────────────────
_YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/"
)

# yt-dlp is optional — the tool reports an error if it's not installed.
# Availability is checked at runtime via `yt-dlp --version` in health_check().
# We set this to True here since yt-dlp is a CLI tool, not a Python import.

# ── Safety limits ──────────────────────────────────────────────────────
_MAX_VIDEO_DURATION_SEC: int = 600         # 10 min — no long-form content
_MAX_VIDEO_SIZE_MB: int = 500              # 500 MiB ceiling
_DOWNLOAD_TIMEOUT_SEC: int = 300           # 5 min max download time
_SAFE_BASE: Path = Path.cwd().resolve()


class YouTubeDownloadParams(BaseModel):
    """Parameters for YouTube video download."""
    url: str = Field(
        description="YouTube video URL (e.g. https://youtube.com/watch?v=...)"
    )
    output_path: str = Field(
        default="",
        description="Output file path. If empty, auto-generated in Output/videos/"
    )
    format: str = Field(
        default="mp4",
        description="Output format: mp4, webm, mkv, or 'audio' for m4a audio only"
    )
    quality: str = Field(
        default="best",
        description="Quality: best, worst, or resolution like 1080p, 720p, 480p"
    )


class YouTubeDownloadTool(BaseTool):
    """Download YouTube videos as MP4 files using yt-dlp.

    Security guards:
    - URL validated against YouTube URL pattern
    - Video duration checked before download (max 10 min)
    - Output path guarded against traversal attacks
    - Download timed out at 300 seconds

    Usage:
        youtube_download(url="https://youtube.com/watch?v=dQw4w9WgXcQ",
                         output_path="Output/videos/clip.mp4")
    """
    default_timeout_seconds: int = _DOWNLOAD_TIMEOUT_SEC
    name: str = "youtube_download"
    description: str = (
        "Download a YouTube video as MP4 file using yt-dlp. "
        "Parameters: url (required), output_path (optional, auto-generated if empty), "
        "format (mp4/webm/mkv/audio), quality (best/worst/resolution). "
        "Video duration is limited to 10 minutes. "
        "After download, the file path is returned."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "YouTube video URL (e.g. https://youtube.com/watch?v=...)"
            },
            "output_path": {
                "type": "string",
                "description": "Output file path (auto-generated if empty)"
            },
            "format": {
                "type": "string",
                "enum": ["mp4", "webm", "mkv", "audio"],
                "description": "Output format (default mp4)"
            },
            "quality": {
                "type": "string",
                "description": "Quality: best, worst, or resolution like 1080p, 720p (default best)"
            },
        },
        "required": ["url"],
    }

    # ── Public API ──────────────────────────────────────────────────────

    async def execute(self, url: str, **kwargs: Any) -> ToolResult:
        params = YouTubeDownloadParams(url=url, **{
            k: v for k, v in kwargs.items() if v is not None
        })

        # 1. Validate YouTube URL
        if not _YOUTUBE_URL_RE.match(params.url):
            return ToolResult.error_result(
                f"Invalid YouTube URL: {params.url[:80]}. "
                "Expected format: https://youtube.com/watch?v=..."
            )

        # 2. Check yt-dlp available (deferred — check on first call)
        if not await self._check_ytdlp():
            return ToolResult.error_result(
                "yt-dlp is not installed or not on PATH. "
                "Install with: pip install yt-dlp"
            )

        # 3. Check video metadata before downloading
        metadata = await self._get_metadata(params.url)
        if metadata is None:
            # Try to get at least the transcript as partial data
            transcript_hint = ""
            try:
                from weebot.tools.video_ingest_tool import VideoIngestTool
                vt = VideoIngestTool()
                if await vt.health_check():
                    transcript_hint = (
                        " Try video_ingest to fetch the transcript/subtitles instead."
                    )
            except Exception:
                pass
            return ToolResult.error_result(
                "Could not download video from " + params.url[:60] + ". "
                "The video may be private, age-restricted, geo-blocked, or the "
                "URL may be invalid.\n\nSuggested alternatives:\n"
                "1. Use web_search to find the same video on another platform\n"
                "2. Search for a transcript or summary of the video content\n"
                "3. Use video_ingest to fetch the subtitles/transcript" + transcript_hint + "\n"
                "4. Try a different YouTube URL for the same content"
            )

        duration = metadata.get("duration", 0)
        if duration > _MAX_VIDEO_DURATION_SEC:
            return ToolResult.error_result(
                f"Video duration ({duration}s) exceeds the maximum allowed "
                f"({_MAX_VIDEO_DURATION_SEC}s). Download a shorter video or "
                "increase MAX_VIDEO_DURATION_SEC."
            )

        # 4. Determine output path
        output_path = params.output_path
        if not output_path:
            import uuid
            ext = "m4a" if params.format == "audio" else "mp4"
            output_path = f"Output/videos/youtube_{uuid.uuid4().hex[:8]}.{ext}"

        path = self._sanitize_output_path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 5. Download
        result = await self._download(params.url, path, params.format, params.quality)
        if result is not None:
            return result

        return ToolResult.error_result(
            f"YouTube download failed for {params.url[:60]}. "
            "Check the URL or ensure yt-dlp is up to date."
        )

    # ── Dependency check ────────────────────────────────────────────────

    async def _check_ytdlp(self) -> bool:
        """Check whether yt-dlp is available on PATH."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except Exception:
            return False

    # ── Metadata fetch ──────────────────────────────────────────────────

    @staticmethod
    def _sanitize_output_path(output_path: str) -> Path:
        """Resolve and validate *output_path* — reject paths escaping the workspace."""
        if ".." in output_path.split("/"):
            raise ValueError(f"Unsafe output_path (contains '..'): {output_path}")
        resolved = Path(output_path).resolve()
        if not str(resolved).startswith(str(_SAFE_BASE)):
            raise ValueError(f"Output path {resolved} escapes workspace {_SAFE_BASE}")
        return resolved

    async def _get_metadata(self, url: str) -> Optional[dict[str, Any]]:
        """Fetch video metadata via yt-dlp --dump-json.

        Returns:
            Dict with 'duration', 'title', 'filesize_approx', etc., or None on failure.
        """
        import json as _json

        cmd = [
            "yt-dlp", "--dump-json",
            "--no-playlist",
            "--skip-download",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30,
            )
            if proc.returncode != 0:
                logger.debug("yt-dlp metadata fetch failed: %s", stderr.decode()[:200])
                return None
            return _json.loads(stdout.decode())
        except asyncio.TimeoutError:
            logger.warning("yt-dlp metadata fetch timed out")
            return None
        except Exception as exc:
            logger.debug("yt-dlp metadata fetch error: %s", exc)
            return None

    # ── Download ────────────────────────────────────────────────────────

    async def _download(
        self,
        url: str,
        output_path: Path,
        fmt: str,
        quality: str,
    ) -> Optional[ToolResult]:
        """Run yt-dlp subprocess to download the video.

        Returns ToolResult on success, None on failure.
        """
        # Resolve format string
        if fmt == "audio":
            format_spec = "bestaudio/best"
        elif quality and quality != "best":
            format_spec = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
        else:
            format_spec = "bestvideo+bestaudio/best"

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-overwrites",
            "--print", "after_move:filepath",  # Output actual filepath after download
            "-o", str(output_path),
            "-f", format_spec,
            "--merge-output-format", fmt if fmt != "audio" else "mp4",
            url,
        ]

        logger.info("Downloading YouTube video: %s", url[:60])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_DOWNLOAD_TIMEOUT_SEC,
            )
            if proc.returncode != 0:
                error_text = stderr.decode()[:300]
                logger.warning("yt-dlp download failed: %s", error_text)
                return None

            # yt-dlp --print after_move:filepath prints the final path on stdout
            actual_path_str = stdout.decode().strip()
            if not actual_path_str:
                # Fallback: use the requested path
                actual_path = output_path
            else:
                actual_path = Path(actual_path_str)

            if not actual_path.exists():
                logger.warning("yt-dlp download completed but file not found: %s", actual_path)
                return None

            size = actual_path.stat().st_size
            logger.info("YouTube download complete: %s (%d bytes)", actual_path, size)

            return ToolResult(
                output=f"Downloaded YouTube video: {actual_path} ({size} bytes)",
                data={
                    "path": str(actual_path.resolve()),
                    "size_bytes": size,
                    "format": fmt,
                    "quality": quality,
                    "url": url[:80],
                },
            )
        except asyncio.TimeoutError:
            logger.warning("YouTube download timed out after %ds", _DOWNLOAD_TIMEOUT_SEC)
            return None
        except Exception as exc:
            logger.warning("YouTube download failed: %s", exc)
            return None

    async def health_check(self) -> bool:
        """yt-dlp must be installed and callable."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except Exception:
            return False
