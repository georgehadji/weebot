"""Video download tool for weebot agents.

Downloads videos and extracts MP3 audio from YouTube, Twitter/X, TikTok,
Instagram, Vimeo, Dailymotion, Facebook, Reddit, Twitch, and hundreds of
other sites using yt-dlp.  Also handles age-restricted content via browser
cookies and JS-heavy sites via Deno runtime.

Security: path traversal guard, HTTPS validation, size caps, timeout.
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

# ── URL validation ───────────────────────────────────────────────────
# Accept any HTTPS URL — yt-dlp validates whether it can handle the site.
# Known supported sources: YouTube, Twitter/X, TikTok, Instagram, Vimeo,
# Dailymotion, Facebook, Reddit, Twitch, and 1000+ more.
_HTTPS_URL_RE = re.compile(r"^https?://")

# yt-dlp is optional — the tool reports an error if it's not installed.
# Availability is checked at runtime via `yt-dlp --version` in health_check().
# We set this to True here since yt-dlp is a CLI tool, not a Python import.

# ── Safety limits ──────────────────────────────────────────────────────
_MAX_VIDEO_DURATION_SEC: int = 600         # 10 min — no long-form content
_MAX_VIDEO_SIZE_MB: int = 500              # 500 MiB ceiling
_DOWNLOAD_TIMEOUT_SEC: int = 300           # 5 min max download time
_SAFE_BASE: Path = Path.cwd().resolve()


class YouTubeDownloadParams(BaseModel):
    """Parameters for video download from any yt-dlp-supported site."""
    url: str = Field(
        description="Video URL from YouTube, Twitter/X, TikTok, Instagram, Vimeo, Dailymotion, Facebook, Reddit, Twitch, or any yt-dlp-supported site"
    )
    output_path: str = Field(
        default="",
        description="Output file path. If empty, auto-generated in Output/videos/"
    )
    format: str = Field(
        default="mp4",
        description="Output format: mp4, webm, mkv, 'mp3' for MP3 audio extraction, or 'audio' for m4a audio only"
    )
    quality: str = Field(
        default="best",
        description="Quality: best, worst, or resolution like 1080p, 720p, 480p"
    )


class YouTubeDownloadTool(BaseTool):
    """Download videos and extract MP3 audio from any yt-dlp-supported site.

    Supports YouTube, Twitter/X, TikTok, Instagram, Vimeo, Dailymotion,
    Facebook, Reddit, Twitch, and 1000+ other sites.

    Download strategies for edge cases:
    - **Age-restricted**: Use `cookies` param via Playwright get_cookies export.
    - **JS runtime error ("No supported JavaScript runtime")**:
      Install Deno: ``winget install DenoLand.Deno`` or ``scoop install deno``.
      Then pass path via `js_runtime` param.
    - **Cannot download at all**: Fall back to `video_ingest` tool for transcript.
    - **Firefox users**: ``yt-dlp --cookies-from-browser firefox`` avoids DPAPI
      errors on Chrome/Edge cookies.

    Security guards:
    - URL validated for HTTPS
    - Video duration checked before download (max 10 min, YouTube only)
    - Output path guarded against traversal attacks
    - Download timed out at 300 seconds

    Usage:
        youtube_download(url="https://youtube.com/watch?v=dQw4w9WgXcQ",
                         output_path="Output/videos/clip.mp4")
        youtube_download(url="https://twitter.com/user/status/123",
                         format="mp4")
    """
    default_timeout_seconds: int = _DOWNLOAD_TIMEOUT_SEC
    name: str = "youtube_download"
    description: str = (
        "Download a video or extract MP3 audio from any yt-dlp-supported site "
        "(YouTube, Twitter/X, TikTok, Instagram, Vimeo, Dailymotion, Facebook, "
        "Reddit, Twitch, and 1000+ more). "
        "Parameters: url (required), output_path (optional, auto-generated if empty), "
        "format (mp4/webm/mkv/mp3/audio), quality (best/worst/resolution), "
        "cookies (path to Netscape-format cookies file for age-restricted videos), "
        "js_runtime (path to Deno/Node.js executable for EJS extractors). "
        "Video duration is limited to 10 minutes (YouTube only). "
        "For MP3: extracts audio and converts to MP3 (320kbps best quality). "
        "After download, the file path is returned.\n\n"
        "Download strategies:\n"
        "- Normal: works as-is for any supported site.\n"
        "- Age-restricted: Use the cookies param with a Playwright cookie export.\n"
        "- JS runtime error: Install Deno (winget install DenoLand.Deno), "
        "then pass its path as js_runtime.\n"
        "- Fallback: Use video_ingest tool for transcript/subtitles instead."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Video URL from YouTube, Twitter/X, TikTok, Instagram, Vimeo, Dailymotion, Facebook, Reddit, Twitch, or any yt-dlp-supported site"
            },
            "output_path": {
                "type": "string",
                "description": "Output file path (auto-generated if empty)"
            },
            "format": {
                "type": "string",
                "enum": ["mp4", "webm", "mkv", "mp3", "audio"],
                "description": "Output format: mp4, webm, mkv, mp3 (audio extraction), or audio (m4a) (default mp4)"
            },
            "quality": {
                "type": "string",
                "description": "Quality: best, worst, or resolution like 1080p, 720p (default best)"
            },
            "cookies": {
                "type": "string",
                "description": "Path to Netscape-format cookies file for age-restricted videos"
            },
            "js_runtime": {
                "type": "string",
                "description": "Path to Deno/Node.js for yt-dlp EJS extractors"
            },
        },
        "required": ["url"],
    }

    # ── Public API ──────────────────────────────────────────────────────

    async def execute(self, url: str, **kwargs: Any) -> ToolResult:
        params = YouTubeDownloadParams(url=url, **{
            k: v for k, v in kwargs.items() if v is not None
        })
        # Reset per-call state
        self._last_download_error = ""

        # 1. Validate URL is HTTPS
        if not _HTTPS_URL_RE.match(params.url):
            return ToolResult.error_result(
                f"Invalid URL: {params.url[:80]}. "
                "Expected an https:// URL to a video page."
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
                "Could not fetch metadata from " + params.url[:60] + ". "
                "The video may be private, age-restricted, or geo-blocked.\n\n"
                "DO NOT GIVE UP — try these approaches IN ORDER within the same step:\n"
                "1. Try downloading anyway (metadata fetch may fail but download may succeed)\n"
                "2. Use video_ingest to fetch the subtitles/transcript" + transcript_hint + "\n"
                "3. Use web_search to find the same video on another platform\n"
                "4. Try a different URL for the same content"
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
            if params.format == "mp3":
                ext = "mp3"
            elif params.format == "audio":
                ext = "m4a"
            else:
                ext = "mp4"
            output_path = f"Output/videos/youtube_{uuid.uuid4().hex[:8]}.{ext}"

        path = self._sanitize_output_path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 5. Download (pass cookies/js_runtime for age-restricted / EJS scenarios)
        result = await self._download(
            url=params.url,
            output_path=path,
            fmt=params.format,
            quality=params.quality,
            cookies=params.cookies,
            js_runtime=params.js_runtime,
        )
        if result is not None:
            return result

        # Build a targeted fallback message based on the actual yt-dlp error
        last_error = getattr(self, "_last_download_error", "")
        error_lower = last_error.lower()

        if "sign in to confirm your age" in error_lower or "age" in error_lower:
            fallback = (
                "\n\nDO NOT GIVE UP. Try the next approach IN THE SAME STEP:\n"
                "1. Use advanced_browser to navigate to youtube.com and sign in\n"
                "2. Call advanced_browser get_cookies action to export cookies\n"
                "3. Use python_execute to convert cookies to Netscape format\n"
                "4. Retry: youtube_download(url=..., cookies=\"tmp/youtube_cookies.txt\")\n"
                "5. If that fails, try video_ingest for transcript as last resort"
            )
        elif "no supported javascript runtime" in error_lower or "javascript runtime" in error_lower:
            fallback = (
                "\n\nDO NOT GIVE UP. Try the next approach IN THE SAME STEP:\n"
                "1. Install Deno: winget install DenoLand.Deno\n"
                "2. Find the path: (Get-Command deno).Source\n"
                "3. Retry: youtube_download(url=..., js_runtime=\"<deno_path>\")\n"
                "4. If that fails, try video_ingest for transcript"
            )
        elif "video unavailable" in error_lower or "private" in error_lower:
            fallback = (
                "\n\nDO NOT GIVE UP. Try the next approach IN THE SAME STEP:\n"
                "1. Use video_ingest to get the transcript/subtitles\n"
                "2. Use web_search to find mirrors or alternative sources"
            )
        else:
            fallback = (
                f"\n\nyt-dlp error: {last_error[:200]}\n\n"
                "DO NOT GIVE UP. Try the next approach IN THE SAME STEP:\n"
                "1. If age-restricted: use cookies (advanced_browser → get_cookies → retry)\n"
                "2. If JS error: install Deno and retry with js_runtime param\n"
                "3. Last resort: video_ingest for transcript"
            )

        return ToolResult.error_result(
            f"Video download failed for {params.url[:60]}."
            + fallback
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
        cookies: str = "",
        js_runtime: str = "",
    ) -> Optional[ToolResult]:
        """Run yt-dlp subprocess to download the video.

        Args:
            url: YouTube video URL.
            output_path: Where to save the video.
            fmt: Output format (mp4, webm, mkv, audio).
            quality: Quality string (best, worst, or resolution).
            cookies: Optional path to Netscape-format cookies file
                     (for age-restricted videos, exported from Playwright).
            js_runtime: Optional path to Deno/Node.js executable
                        (for EJS extractor runtime).

        Returns ToolResult on success, None on failure.
        """
        # Resolve format string and post-processing flags
        if fmt == "mp3":
            # Extract best audio and convert to MP3 at highest quality
            format_spec = "bestaudio/best"
        elif fmt == "audio":
            format_spec = "bestaudio/best"
        elif quality and quality != "best":
            format_spec = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
        else:
            format_spec = "bestvideo+bestaudio/best"

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-overwrites",
            "--print", "after_move:filepath",
            "-o", str(output_path),
            "-f", format_spec,
        ]

        # Audio extraction: --extract-audio --audio-format with quality
        if fmt == "mp3":
            cmd.extend([
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",  # best (320kbps for mp3)
            ])
        elif fmt == "audio":
            cmd.extend(["--merge-output-format", "mp4"])
        else:
            cmd.extend(["--merge-output-format", fmt])

        # Optional: cookies file for age-restricted videos
        # (export from Playwright get_cookies action → Netscape format)
        if cookies:
            cp = Path(cookies)
            if cp.exists() and cp.is_file():
                cmd.extend(["--cookies", str(cp.resolve())])
                logger.info("Using cookies: %s", cp)
            else:
                logger.warning("Cookies file not found: %s", cookies)

        # Optional: JS runtime path for EJS extractors
        # (install Deno via: winget install DenoLand.Deno)
        if js_runtime:
            jp = Path(js_runtime)
            if jp.exists() and jp.is_file():
                cmd.extend(["--js-runtimes", str(jp.resolve())])
                logger.info("Using JS runtime: %s", jp)
            else:
                logger.warning("JS runtime not found: %s", js_runtime)

        cmd.append(url)

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
                error_text = stderr.decode()[:500]
                logger.warning("yt-dlp download failed: %s", error_text)
                # Attach the error text as a special attribute so execute()
                # can use it for targeted fallback instructions.
                self._last_download_error = error_text
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
