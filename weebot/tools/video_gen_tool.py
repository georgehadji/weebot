"""Video generation tool for weebot agents.

Generates short video clips via OpenRouter video models (Kling, Veo, Seedance,
Hailuo, Wan, Grok Imagine Video, Sora) and direct xAI API.

All video models are accessed through OpenRouter's chat completions API with
modalities hinting for video output. The returned URL is downloaded and saved
as an MP4 file.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from weebot.tools.base import BaseTool, ToolResult
from weebot.config.api_endpoints import XAI_API_BASE


class VideoGenParams(BaseModel):
    """Parameters for video generation."""
    prompt: str = Field(
        default="",
        description="Text description of the video to generate"
    )
    model: str = Field(
        default="",
        description="OpenRouter video model ID. Leave empty to auto-select from cascade based on use_case."
    )
    use_case: str = Field(
        default="general",
        description="Use case for auto model selection: short, cinematic, product, brand, general"
    )
    output_path: str = Field(
        default="",
        description="File path to write the MP4 to (e.g. 'Output/videos/demo.mp4')"
    )
    duration_seconds: int = Field(
        default=5,
        description="Target video duration in seconds (model-dependent, not all models support exact duration)"
    )


# ── Custom video model mappings ─────────────────────────────────────
# Models that need special handling (e.g. direct API path vs OpenRouter)
_XAI_VIDEO_PATTERN = re.compile(r"^x-ai/")


class VideoGenTool(BaseTool):
    """Generate short video clips using OpenRouter video models.

    Supports OpenRouter's video-capable chat completion models:
    Kling (Kwaivgi), Google Veo, ByteDance Seedance, MiniMax Hailuo,
    Alibaba Wan, xAI Grok Imagine Video, and OpenAI Sora.

    Usage:
        video_gen(prompt="A cat walking on a beach at sunset", output_path="Output/videos/cat.mp4")

    The tool:
    1. Selects a model (explicit or from cascade by use_case)
    2. Sends a chat completion request with video output modality
    3. Downloads the generated video from the returned URL
    4. Saves it as MP4 to the specified output path
    """
    default_timeout_seconds: int = 180
    name: str = "video_gen"
    description: str = (
        "Generate short video clips from text descriptions using AI video models. "
        "Supported models (via OpenRouter): Kling Video, Google Veo, ByteDance Seedance, "
        "MiniMax Hailuo, Alibaba Wan, xAI Grok Imagine Video, OpenAI Sora. "
        "Parameters: prompt (required), output_path (required), model (optional override), "
        "use_case (auto-select cascade: short/cinematic/product/brand/general). "
        "Saves output as MP4 file and returns the file path."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text description of the video to generate"
            },
            "model": {
                "type": "string",
                "description": "OpenRouter video model ID. If omitted, auto-selects from the video cascade based on use_case."
            },
            "use_case": {
                "type": "string",
                "enum": ["short", "cinematic", "product", "brand", "general"],
                "description": "Use case for auto model selection. Cascade: short→seedance-fast, cinematic→sora/veo, product→wan/kling, brand→grok/veo, general→grok/kling/wan"
            },
            "output_path": {
                "type": "string",
                "description": "File path for the output MP4 file (required). E.g. 'Output/videos/demo.mp4'"
            },
            "duration_seconds": {
                "type": "integer",
                "description": "Target video duration in seconds (model-dependent, default 5)"
            },
        },
        "required": ["prompt", "output_path"],
    }

    # ── Direct xAI video generation ──────────────────────────────────

    async def _execute_xai_direct(
        self,
        prompt: str,
        output_path: str,
        xai_key: str,
    ) -> ToolResult | None:
        """Call xAI's video generation endpoint directly.

        Uses the xAI chat completions API with x-ai/grok-imagine-video
        as the model parameter, requesting video output.

        Returns:
            ToolResult on success, None on failure (caller should fall back).
        """
        import asyncio as _asyncio
        import aiohttp

        headers = {
            "Authorization": f"Bearer {xai_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": "grok-imagine-video",
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{XAI_API_BASE}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=180),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        _log = __import__("logging").getLogger(__name__)
                        _log.debug("xAI video gen failed: HTTP %s — %s", resp.status, error_text[:150])
                        return None

                    result = await resp.json()
                    video_url = self._extract_video_url(result)
                    if not video_url:
                        return None

                    return await self._download_video(video_url, output_path, "x-ai/grok-imagine-video", prompt)

        except _asyncio.TimeoutError:
            return None
        except Exception:
            return None

    # ── OpenRouter video generation ──────────────────────────────────

    @staticmethod
    def _extract_video_url(result: dict) -> str:
        """Extract video URL from an OpenRouter/xAI video model response."""
        choices = result.get("choices", [{}])
        if not choices:
            return ""
        message = choices[0].get("message", {})

        # Try images array (OpenRouter returns video URLs in images array)
        images = message.get("images", [])
        if images:
            img = images[0]
            if isinstance(img, dict):
                return img.get("image_url", {}).get("url", "")
            return str(img)

        # Try content blocks
        content = message.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        return part.get("image_url", {}).get("url", "")
                    if part.get("type") == "video_url":
                        return part.get("video_url", {}).get("url", "")
                    if part.get("url"):
                        return part["url"]
                    if part.get("data"):
                        return part["data"]

        # Fallback: check the full response for a video_url or url field
        video_url = result.get("video_url", "") or result.get("url", "")
        if video_url:
            return video_url

        # Last resort: check content string for a URL
        if isinstance(content, str):
            url_match = re.search(r"https?://[^\s\"']+\.(mp4|webm|mov|avi)", content)
            if url_match:
                return url_match.group(0)

        return ""

    async def _download_video(
        self,
        video_url: str,
        output_path: str,
        model: str,
        prompt: str,
    ) -> ToolResult | None:
        """Download a video from a URL and save it to disk."""
        import aiohttp

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                    if resp.status != 200:
                        return None
                    path.write_bytes(await resp.read())
        except Exception:
            return None

        size = path.stat().st_size
        return ToolResult(
            output=f"Generated video via {model}: {output_path} ({size} bytes)",
            data={
                "path": str(path.resolve()),
                "model": model,
                "kind": "video",
                "size_bytes": size,
                "format": path.suffix.lstrip("."),
                "prompt": prompt,
            },
        )

    async def _execute_openrouter(self, params: VideoGenParams) -> ToolResult:
        """Call video models via OpenRouter with cascade fallback.

        Resolution order:
        1. xAI direct (if model is x-ai/* and XAI_API_KEY is set)
        2. Explicit model via OpenRouter (if provided)
        3. Cascade based on use_case
        4. Generic fallback message
        """
        import asyncio as _asyncio
        import aiohttp

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        xai_key = os.getenv("XAI_API_KEY", "")
        prompt = params.prompt
        output_path = params.output_path

        if not output_path:
            output_path = f"Output/videos/video_{uuid.uuid4().hex[:8]}.mp4"

        # ── Determine model list ──────────────────────────────────
        models_to_try: list[str]
        if params.model:
            models_to_try = [params.model]
        else:
            from weebot.config.model_refs import VIDEO_CASCADE
            use_case = params.use_case or "general"
            cascade = VIDEO_CASCADE.get(use_case, VIDEO_CASCADE["general"])
            models_to_try = list(cascade)

        if not api_key and not xai_key:
            return ToolResult.error_result(
                "Video generation requires OPENROUTER_API_KEY or XAI_API_KEY. "
                "Set one of these in your .env file."
            )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/weebot",
            "X-Title": "weebot",
        }

        last_error = None

        for model in models_to_try:
            # ── Try xAI direct for x-ai/* models ───────────────────
            if _XAI_VIDEO_PATTERN.match(model) and xai_key:
                xai_result = await self._execute_xai_direct(
                    prompt=prompt,
                    output_path=output_path,
                    xai_key=xai_key,
                )
                if xai_result is not None:
                    return xai_result

            if not api_key:
                last_error = f"{model}: no OPENROUTER_API_KEY"
                continue

            # ── OpenRouter chat completion ─────────────────────────
            payload: dict = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=180),
                    ) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            last_error = f"{model}: HTTP {resp.status} — {error_text[:150]}"
                            continue

                        result = await resp.json()
                        video_url = self._extract_video_url(result)
                        if not video_url:
                            last_error = f"{model}: no video URL in response"
                            continue

                        download_result = await self._download_video(
                            video_url, output_path, model, prompt,
                        )
                        if download_result is not None:
                            return download_result
                        last_error = f"{model}: download failed"

            except _asyncio.TimeoutError:
                last_error = f"{model}: timed out (180s)"
                continue
            except Exception as exc:
                last_error = f"{model}: {exc}"
                continue

        # All models failed
        fallback_msg = (
            f"Video generation failed. All {len(models_to_try)} model(s) tried"
        )
        if last_error:
            fallback_msg += f". Last error: {last_error}"
        return ToolResult.error_result(fallback_msg)

    async def health_check(self) -> bool:
        """VideoGenTool needs at least one API key to function."""
        return bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("XAI_API_KEY"))

    async def execute(self, **kwargs: Any) -> ToolResult:
        params = VideoGenParams(**{k: v for k, v in kwargs.items() if v is not None})

        if not params.prompt:
            return ToolResult.error_result("prompt is required for video generation")
        if not params.output_path:
            return ToolResult.error_result("output_path is required")

        return await self._execute_openrouter(params)
