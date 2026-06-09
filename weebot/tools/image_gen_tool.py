"""Image generation tool for weebot agents.

Generates images as SVG code, CSS art, or placeholder graphics.
Designed for website building — produces clean, scalable, self-contained
SVG files that render in any browser without external dependencies.

For raster image generation (PNG/JPG), integrates with Replicate API
as an optional backend when REPLICATE_API_TOKEN is configured.
"""
from __future__ import annotations

import base64
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from weebot.tools.base import BaseTool, ToolResult
from weebot.config.api_endpoints import XAI_IMAGE_GENERATION_URL

_SVG_SANITIZE_RE = re.compile(r'[<>"\']')

# Replicate is optional — only needed for raster image generation
try:
    import replicate as _replicate
    _REPLICATE_AVAILABLE = True
except ImportError:
    _REPLICATE_AVAILABLE = False


# ── SVG template library for common website use-cases ────────────────

_HERO_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1200" height="600">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{primary};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{secondary};stop-opacity:1" />
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:{accent_color};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{accent_color}80;stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="1200" height="600" fill="url(#bg)" />
  <circle cx="150" cy="150" r="300" fill="{accent_color}" opacity="0.08" />
  <circle cx="1050" cy="450" r="250" fill="{accent_color}" opacity="0.06" />
  <circle cx="600" cy="300" r="180" fill="none" stroke="{accent_color}" stroke-width="2" opacity="0.15" />
  <circle cx="600" cy="300" r="120" fill="none" stroke="{accent_color}" stroke-width="3" opacity="0.2" />
  <rect x="520" y="250" width="160" height="100" rx="12" fill="url(#accent)" opacity="0.9" />
  <text x="600" y="290" text-anchor="middle" fill="white" font-family="system-ui, sans-serif" font-size="16" font-weight="700">{icon}</text>
  <text x="600" y="315" text-anchor="middle" fill="white" font-family="system-ui, sans-serif" font-size="11" opacity="0.9">{label}</text>
  <text x="600" y="450" text-anchor="middle" fill="white" font-family="Georgia, serif" font-size="36" font-weight="700">{title}</text>
  <text x="600" y="490" text-anchor="middle" fill="white" font-family="system-ui, sans-serif" font-size="16" opacity="0.75">{subtitle}</text>
</svg>'''

_CARD_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" width="400" height="300">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{primary};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{secondary};stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="400" height="300" rx="16" fill="url(#bg)" />
  <rect x="30" y="30" width="60" height="60" rx="14" fill="{accent_color}" opacity="0.2" />
  <text x="60" y="68" text-anchor="middle" fill="{accent_color}" font-family="system-ui, sans-serif" font-size="28">{icon}</text>
  <text x="30" y="130" fill="white" font-family="Georgia, serif" font-size="20" font-weight="700">{title}</text>
  <text x="30" y="155" fill="white" font-family="system-ui, sans-serif" font-size="11" opacity="0.65">
    {desc_line1}
  </text>
  <text x="30" y="172" fill="white" font-family="system-ui, sans-serif" font-size="11" opacity="0.65">
    {desc_line2}
  </text>
  <text x="30" y="189" fill="white" font-family="system-ui, sans-serif" font-size="11" opacity="0.65">
    {desc_line3}
  </text>
</svg>'''

_ICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="80" height="80">
  <rect width="80" height="80" rx="18" fill="{primary}" />
  <text x="40" y="52" text-anchor="middle" fill="{accent_color}" font-family="system-ui, sans-serif" font-size="34">{icon}</text>
</svg>'''

_LOGO_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 60" width="200" height="60">
  <rect width="200" height="60" rx="10" fill="{primary}" />
  <text x="100" y="39" text-anchor="middle" fill="white" font-family="Georgia, serif" font-size="22" font-weight="700" letter-spacing="2">{text}</text>
</svg>'''

_TESTIMONIAL_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120">
  <defs>
    <linearGradient id="av" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{primary};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{secondary};stop-opacity:1" />
    </linearGradient>
  </defs>
  <circle cx="60" cy="60" r="60" fill="url(#av)" />
  <text x="60" y="72" text-anchor="middle" fill="white" font-family="system-ui, sans-serif" font-size="40" font-weight="600">{initials}</text>
</svg>'''


class ImageGenParams(BaseModel):
    """Parameters for image generation."""
    kind: str = Field(
        default="hero",
        description="Type: 'hero', 'card', 'icon', 'logo', 'testimonial', 'svg', 'ai', 'openrouter'"
    )
    model: str = Field(
        default="",
        description="OpenRouter image model ID (for kind='openrouter'). Leave empty to auto-select from cascade based on use_case."
    )
    use_case: str = Field(
        default="general",
        description="Use case for auto model selection: hero, logo, icon, photo, diagram, social, text, brand, general"
    )
    output_path: str = Field(
        default="",
        description="File path to write the SVG/PNG to (e.g. 'public/images/hero.svg')"
    )
    prompt: str = Field(
        default="",
        description="Description for AI-generated images (only used with kind='ai' or 'svg')"
    )
    primary_color: str = Field(default="#1a1a2e", description="Primary/background hex color")
    secondary_color: str = Field(default="#16213e", description="Secondary/gradient hex color")
    accent_color: str = Field(default="#e94560", description="Accent hex color")
    title: str = Field(default="", description="Title text for hero/card images")
    subtitle: str = Field(default="", description="Subtitle text")
    icon: str = Field(default="★", description="Single emoji or character for the icon")
    label: str = Field(default="", description="Label text for icon badge")
    initials: str = Field(default="AB", description="Initials for testimonial avatars (max 2 chars)")
    text: str = Field(default="LOGO", description="Text for logo SVGs")
    width: int = Field(default=1200, description="SVG width")
    height: int = Field(default=600, description="SVG height")


# ── Prompt-driven SVG themes (used when APIs are unavailable) ────────
_SVG_THEMES: dict = {
        "hero": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            '<rect width="100%" height="100%" fill="{bg}"/>'
            '<rect x="40" y="40" width="{w_minus}" height="{h_minus}" fill="none" stroke="{accent}" stroke-width="6"/>'
            '<rect x="60" y="60" width="{w_minus2}" height="{h_minus2}" fill="none" stroke="{fg}" stroke-width="2" opacity="0.3"/>'
            '<circle cx="{cx}" cy="{cy}" r="60" fill="none" stroke="{accent}" stroke-width="3" opacity="0.4"/>'
            '<text x="{cx}" y="{cy_plus}" text-anchor="middle" fill="{fg}" font-family="Impact,sans-serif" font-size="48" font-weight="700">{title}</text>'
            '<text x="{cx}" y="{sub_y}" text-anchor="middle" fill="{fg}" font-family="monospace" font-size="16" opacity="0.7">{subtitle}</text>'
            '</svg>'
        ),
        "card": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            '<rect width="100%" height="100%" fill="{bg}"/>'
            '<rect x="20" y="20" width="{w_minus}" height="{h_minus}" fill="{fg}" opacity="0.05" stroke="{accent}" stroke-width="3" rx="0"/>'
            '<rect x="20" y="20" width="8" height="{h_minus}" fill="{accent}"/>'
            '<text x="50" y="{h_half}" fill="{fg}" font-family="Impact,sans-serif" font-size="24" font-weight="700">{title}</text>'
            '<text x="50" y="{sub_y}" fill="{fg}" font-family="monospace" font-size="12" opacity="0.6">{subtitle}</text>'
            '</svg>'
        ),
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            '<rect width="100%" height="100%" fill="{bg}" rx="16"/>'
            '<circle cx="{cx}" cy="{cx}" r="{r}" fill="none" stroke="{accent}" stroke-width="4"/>'
            '<text x="{cx}" y="{cy_plus}" text-anchor="middle" fill="{fg}" font-family="Impact,sans-serif" font-size="24" font-weight="700">{title}</text>'
            '</svg>'
        ),
        "logo": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            '<rect width="100%" height="100%" fill="{bg}"/>'
            '<rect x="20" y="20" width="{w_minus}" height="{h_minus}" fill="none" stroke="{accent}" stroke-width="4" rx="2"/>'
            '<text x="{cx}" y="{cy_plus}" text-anchor="middle" fill="{fg}" font-family="Georgia,serif" font-size="22" font-weight="700" letter-spacing="2">{title}</text>'
            '</svg>'
        ),
        "profile": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            '<rect width="100%" height="100%" fill="{bg}"/>'
            '<circle cx="{cx}" cy="{cx}" r="{r}" fill="{accent}" opacity="0.15"/>'
            '<text x="{cx}" y="{cy_plus}" text-anchor="middle" fill="{fg}" font-family="Impact,sans-serif" font-size="16" font-weight="700">{title}</text>'
            '</svg>'
        ),
        "og": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            '<rect width="100%" height="100%" fill="{bg}"/>'
            '<rect x="0" y="{h_minus_60}" width="100%" height="60" fill="{accent}" opacity="0.8"/>'
            '<text x="{cx}" y="{cx}" text-anchor="middle" fill="{fg}" font-family="Impact,sans-serif" font-size="42" font-weight="700">{title}</text>'
            '<text x="{cx}" y="{sub_y}" text-anchor="middle" fill="{fg}" font-family="monospace" font-size="18" opacity="0.7">{subtitle}</text>'
            '</svg>'
        ),
    }

def _render_themed_svg(
    params,
    theme: str = "hero",
    extra: dict | None = None,
) -> str:
    """Render a prompt-appropriate SVG from a theme template.

    Detects the best theme from the prompt if not explicitly given.
    Falls back to 'hero' for unrecognized keywords.
    """
    prompt = (params.prompt or "").lower()
    _extra = extra or {}
    title = ImageGenTool._sanitize(params.title or _extra.get("title", ""), 40) or "Image"
    subtitle = ImageGenTool._sanitize(params.subtitle or _extra.get("subtitle", ""), 60) or prompt[:60]

    # Auto-detect theme from prompt keywords
    if "avatar" in prompt or "portrait" in prompt or "profile" in prompt:
            theme = "profile"
    elif "icon" in prompt or "favicon" in prompt or "badge" in prompt:
            theme = "icon"
    elif "logo" in prompt or "brand" in prompt:
            theme = "logo"
    elif "og" in prompt or "open graph" in prompt or "social" in prompt or "card" in prompt:
            theme = "og"
    elif "project" in prompt or "thumbnail" in prompt or "card" in prompt:
            theme = "card"

    template = _SVG_THEMES.get(theme, _SVG_THEMES["hero"])
    w, h = params.width or 400, params.height or 400
    return template.format(
            w=w, h=h,
            w_minus=w - 40, w_minus2=w - 120,
            h_minus=h - 40, h_minus2=h - 120,
            h_half=h // 2 - 10, h_minus_60=h - 60,
            cx=w // 2, cy=h // 2 - 20, cy_plus=h // 2 + 10,
            r=min(w, h) // 3,
            sub_y=h // 2 + 40,
            bg=params.primary_color or "#1a1a2e",
            fg=params.accent_color or "#ffffff",
            accent=params.accent_color or "#e94560",
            title=title,
            subtitle=subtitle,
    )


class ImageGenTool(BaseTool):
    """Generate images as SVG for websites, icons, logos, and hero graphics.

    Produces clean, self-contained SVG files that render in any browser.
    Supports template-based generation (hero, card, icon, logo, testimonial)
    and can prompt the LLM to generate custom SVGs.

    For raster image generation (PNG/JPG), requires REPLICATE_API_TOKEN to
    be configured — falls back to SVG generation otherwise.
    """
    name: str = "image_gen"
    description: str = (
        "Generate images for websites: hero banners, cards, icons, logos, "
        "testimonial avatars, custom SVGs, and AI-generated images via OpenRouter. "
        "Use kind='openrouter' with a prompt and model to call text-to-image models "
        "like Sourceful Riverflow (FREE), Flux.2 Pro (photorealistic), Recraft (vectors), "
        "or Gemini Flash Image (diagrams/UI). For template SVGs, use kind='hero', 'card', "
        "'icon', 'logo', or 'testimonial'. "
        "Parameters: kind, output_path (required), prompt, model, "
        "primary_color, secondary_color, accent_color, title, subtitle, "
        "icon (single emoji), initials, text, width, height."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["hero", "card", "icon", "logo", "testimonial", "svg", "ai", "openrouter"],
                "description": "Type of image to generate. 'openrouter' calls an AI image model via OpenRouter."
            },
            "model": {
                "type": "string",
                "description": "OpenRouter image model ID (only for kind='openrouter'). If omitted, auto-selects from the image cascade based on use_case. Explicit model overrides the cascade."
            },
            "use_case": {
                "type": "string",
                "enum": ["hero", "logo", "icon", "photo", "diagram", "social", "text", "brand", "general"],
                "description": "Use case for auto model selection (kind='openrouter' only). Cascade: hero→flux.2-pro, logo→recraft vector, photo→flux.2-max, diagram→gemini, social→riverflow fast, text→seedream, brand→mai-image, general→riverflow free"
            },
            "output_path": {
                "type": "string",
                "description": "File path for the output file (required). E.g. 'Output/images/hero.svg'"
            },
            "prompt": {
                "type": "string",
                "description": "Description for AI-generated images (used with kind='svg' or 'ai')"
            },
            "primary_color": {
                "type": "string",
                "description": "Primary/background color in hex (default: #1a1a2e)"
            },
            "secondary_color": {
                "type": "string",
                "description": "Secondary color for gradients (default: #16213e)"
            },
            "accent_color": {
                "type": "string",
                "description": "Accent/highlight color in hex (default: #e94560)"
            },
            "title": {
                "type": "string",
                "description": "Title text displayed on the image"
            },
            "subtitle": {
                "type": "string",
                "description": "Subtitle/description text"
            },
            "icon": {
                "type": "string",
                "description": "Single emoji or character for icon (e.g. '🦷', '★', '⚕')"
            },
            "label": {
                "type": "string",
                "description": "Label text shown below the icon in hero images"
            },
            "initials": {
                "type": "string",
                "description": "1-2 character initials for testimonial avatars (e.g. 'JD')"
            },
            "text": {
                "type": "string",
                "description": "Text for logo SVGs"
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels (default: 1200)"
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels (default: 600)"
            },
        },
        "required": ["kind", "output_path"],
    }

    @staticmethod
    def _sanitize(text: str, max_len: int = 80) -> str:
        """Clean user-provided text for safe SVG embedding."""
        cleaned = _SVG_SANITIZE_RE.sub("", text or "")
        return cleaned[:max_len].strip()

    @staticmethod
    def _wrap_text(text: str, max_len: int = 35) -> list[str]:
        """Split long text into multiple lines for SVG rendering."""
        words = text.split()
        lines = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= max_len:
                current = (current + " " + word).strip()
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines if lines else [""]

    @classmethod
    def generate_hero(cls, params: ImageGenParams) -> str:
        """Generate a hero banner SVG."""
        return _HERO_SVG.format(
            primary=ImageGenTool._sanitize(params.primary_color, 7),
            secondary=ImageGenTool._sanitize(params.secondary_color, 7),
            accent_color=ImageGenTool._sanitize(params.accent_color, 7),
            icon=ImageGenTool._sanitize(params.icon, 4) or "★",
            label=ImageGenTool._sanitize(params.label, 20) or params.title[:20],
            title=ImageGenTool._sanitize(params.title, 50) or "Your Title Here",
            subtitle=ImageGenTool._sanitize(params.subtitle, 70) or "Your subtitle goes here",
        )

    @classmethod
    def generate_card(cls, params: ImageGenParams) -> str:
        """Generate a feature card SVG."""
        desc_lines = cls._wrap_text(params.subtitle or "Feature description", 35)
        return _CARD_SVG.format(
            primary=ImageGenTool._sanitize(params.primary_color, 7),
            secondary=ImageGenTool._sanitize(params.secondary_color, 7),
            accent_color=ImageGenTool._sanitize(params.accent_color, 7),
            icon=ImageGenTool._sanitize(params.icon, 4) or "★",
            title=ImageGenTool._sanitize(params.title, 25) or "Feature",
            desc_line1=ImageGenTool._sanitize(desc_lines[0] if len(desc_lines) > 0 else "", 35),
            desc_line2=ImageGenTool._sanitize(desc_lines[1] if len(desc_lines) > 1 else "", 35),
            desc_line3=ImageGenTool._sanitize(desc_lines[2] if len(desc_lines) > 2 else "", 35),
        )

    @classmethod
    def generate_icon(cls, params: ImageGenParams) -> str:
        """Generate an icon SVG."""
        return _ICON_SVG.format(
            primary=ImageGenTool._sanitize(params.primary_color, 7),
            accent_color=ImageGenTool._sanitize(params.accent_color, 7),
            icon=ImageGenTool._sanitize(params.icon, 4) or "●",
        )

    @classmethod
    def generate_logo(cls, params: ImageGenParams) -> str:
        """Generate a logo SVG."""
        return _LOGO_SVG.format(
            primary=ImageGenTool._sanitize(params.primary_color, 7),
            text=ImageGenTool._sanitize(params.text.upper(), 20) or "LOGO",
        )

    @classmethod
    def generate_testimonial(cls, params: ImageGenParams) -> str:
        """Generate a testimonial avatar SVG."""
        init = ImageGenTool._sanitize(params.initials.upper(), 2) or "AB"
        return _TESTIMONIAL_SVG.format(
            primary=ImageGenTool._sanitize(params.primary_color, 7),
            secondary=ImageGenTool._sanitize(params.secondary_color, 7),
            initials=init,
        )

    async def _execute_xai_direct(
        self,
        xai_model: str,
        prompt: str,
        output_path: str,
        xai_key: str,
        n: int = 1,
        response_format: str = "url",
    ) -> ToolResult | None:
        """Call xAI's native image generation API.

        Endpoint: POST https://api.x.ai/v1/images/generations
        Uses the OpenAI-compatible images.generate() pattern.

        Args:
            xai_model: Native xAI model name (e.g. "grok-imagine-image-quality").
            prompt: Text description.
            output_path: File path for the output image.
            xai_key: XAI_API_KEY value.
            n: Number of images (1-10, default 1).
            response_format: "url" (default) or "b64_json".

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
            "model": xai_model,
            "prompt": prompt,
            "n": n,
            "response_format": response_format,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    XAI_IMAGE_GENERATION_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        import logging
                        logging.getLogger(__name__).info(
                            "xAI direct image gen failed: HTTP %s — %s",
                            resp.status, error_text[:150],
                        )
                        return None

                    result = await resp.json()
                    data = result.get("data", [])
                    if not data:
                        return None

                    image = data[0]
                    url = image.get("url", "")
                    b64 = image.get("b64_json", "")

                    path = Path(output_path)
                    path.parent.mkdir(parents=True, exist_ok=True)

                    if b64:
                        import base64 as _b64
                        path.write_bytes(_b64.b64decode(b64))
                    elif url.startswith("http"):
                        async with session.get(url) as img_resp:
                            if img_resp.status == 200:
                                path.write_bytes(await img_resp.read())
                            else:
                                return None
                    else:
                        return None

                    size = path.stat().st_size
                    return ToolResult(
                        output=f"Generated image via xAI direct ({xai_model}): {output_path} ({size} bytes)",
                        data={
                            "path": str(path.resolve()),
                            "model": f"x-ai/{xai_model}",
                            "kind": "xai-direct",
                            "size_bytes": size,
                            "format": path.suffix.lstrip("."),
                            "prompt": prompt,
                        },
                    )

        except _asyncio.TimeoutError:
            return None
        except Exception:
            return None

    async def _execute_openrouter(self, params: ImageGenParams) -> ToolResult:
        """Call text-to-image models with cascade fallback.

        Resolution order:
        1. xAI direct (if model is x-ai/* and XAI_API_KEY is set) → try once
        2. Explicit model via OpenRouter (if provided) → try once
        3. Cascade based on use_case → primary → fallback1 → fallback2 (free)
        4. SVG template fallback (always works, no API)
        """
        import asyncio as _asyncio
        import aiohttp

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        xai_key = os.getenv("XAI_API_KEY", "")
        prompt = params.prompt or params.title or "A beautiful, professional image"
        output_path = params.output_path

        if not output_path:
            ext = "png"
            output_path = f"Output/images/openrouter_{uuid.uuid4().hex[:8]}.{ext}"

        # ── Determine model list ──────────────────────────────────
        if params.model:
            models_to_try = [params.model]
        else:
            from weebot.config.model_refs import IMAGE_CASCADE, get_image_model_for
            use_case = getattr(params, "use_case", None) or "general"
            cascade = IMAGE_CASCADE.get(use_case, IMAGE_CASCADE["general"])
            models_to_try = list(cascade)

        if not api_key:
            # No API key — skip straight to SVG fallback
            return await self._fallback_svg(params, output_path, "No OPENROUTER_API_KEY set")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/weebot",
            "X-Title": "weebot",
        }

        last_error = None

        # ── Helper: try xAI direct for x-ai/* models ───────────────
        async def _try_xai_direct(model: str) -> ToolResult | None:
            """Try xAI direct image generation. Returns result on success, None to fall through."""
            if not xai_key or not model.startswith("x-ai/"):
                return None
            xai_model = model.split("/", 1)[-1]  # "x-ai/grok-imagine-image-quality" → "grok-imagine-image-quality"
            return await self._execute_xai_direct(
                xai_model=xai_model,
                prompt=prompt,
                output_path=output_path,
                xai_key=xai_key,
            )

        for model in models_to_try:
            # ── Try xAI direct first for x-ai/* models ─────────────
            xai_result = await _try_xai_direct(model)
            if xai_result is not None:
                return xai_result

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "modalities": ["image", "text"],
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            last_error = f"{model}: HTTP {resp.status} — {error_text[:150]}"
                            continue  # try next model in cascade

                        result = await resp.json()
                        choice = result.get("choices", [{}])[0]
                        message = choice.get("message", {})

                        # Extract image URL/data from response
                        url = self._extract_image_url(message, result)
                        if not url:
                            last_error = f"{model}: no image in response"
                            continue  # try next model

                        # Save the image
                        path = Path(output_path)
                        path.parent.mkdir(parents=True, exist_ok=True)

                        if url.startswith("data:image"):
                            import base64 as _b64
                            _, b64_data = url.split(",", 1)
                            path.write_bytes(_b64.b64decode(b64_data))
                        elif url.startswith("http"):
                            async with session.get(url) as img_resp:
                                if img_resp.status == 200:
                                    path.write_bytes(await img_resp.read())
                                else:
                                    last_error = f"{model}: download failed HTTP {img_resp.status}"
                                    continue
                        else:
                            last_error = f"{model}: unsupported format {url[:80]}"
                            continue

                        size = path.stat().st_size
                        return ToolResult(
                            output=f"Generated image via {model}: {output_path} ({size} bytes)",
                            data={
                                "path": str(path.resolve()),
                                "model": model,
                                "models_tried": models_to_try[:models_to_try.index(model) + 1],
                                "kind": "openrouter",
                                "size_bytes": size,
                                "format": path.suffix.lstrip("."),
                                "prompt": prompt,
                            },
                        )

            except _asyncio.TimeoutError:
                last_error = f"{model}: timed out (120s)"
                continue
            except Exception as exc:
                last_error = f"{model}: {exc}"
                continue

        # All API models failed — fall back to SVG template
        return await self._fallback_svg(
            params, output_path,
            f"All image models failed. Last error: {last_error}"
        )

    @staticmethod
    def _extract_image_url(message: dict, result: dict) -> str:
        """Extract image URL/data from an OpenRouter image model response."""
        # Try images array first
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
                    if part.get("type") == "image":
                        return part.get("source", {}).get("data", "")
        elif isinstance(content, str) and content.startswith("data:image"):
            return content

        return ""

    async def _fallback_svg(self, params: ImageGenParams, output_path: str, reason: str) -> ToolResult:
        """Generate a prompt-driven themed SVG placeholder as ultimate fallback."""
        svg_path = Path(output_path).with_suffix(".svg")
        svg = _render_themed_svg(params)
        svg_path.write_text(svg, encoding="utf-8")
        return ToolResult(
            output=f"SVG fallback: {svg_path} (all API models unavailable: {reason[:80]})",
            data={
                "path": str(svg_path.resolve()),
                "kind": "svg_fallback",
                "size_bytes": len(svg),
                "format": "svg",
                "fallback_reason": reason,
            },
        )

    async def _generate_ai(self, params: ImageGenParams) -> str:
        """Generate an image via Replicate (raster) or return a prompt for LLM SVG generation."""
        if _REPLICATE_AVAILABLE and os.getenv("REPLICATE_API_TOKEN"):
            try:
                output = await _replicate.run(
                    "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                    input={"prompt": params.prompt or params.title, "width": params.width, "height": params.height},
                )
                if output and isinstance(output, list) and output[0]:
                    return output[0]  # URL to generated image
            except Exception as exc:
                return f"<!-- Replicate failed: {exc} -->\n<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {params.width} {params.height}'><rect width='100%' height='100%' fill='{params.primary_color}'/><text x='50%' y='50%' text-anchor='middle' fill='white' font-family='sans-serif' font-size='20'>AI image generation unavailable</text></svg>"

        # Fallback: prompt-driven themed SVG
        return _render_themed_svg(params)

    async def execute(self, **kwargs: Any) -> ToolResult:
        params = ImageGenParams(**{k: v for k, v in kwargs.items() if v is not None})

        # Route to the appropriate generator
        generators = {
            "hero": self.generate_hero,
            "card": self.generate_card,
            "icon": self.generate_icon,
            "logo": self.generate_logo,
            "testimonial": self.generate_testimonial,
        }

        if params.kind in generators:
            svg = generators[params.kind](params)
        elif params.kind in ("svg", "ai"):
            svg = await self._generate_ai(params)
        elif params.kind == "openrouter":
            return await self._execute_openrouter(params)
        else:
            return ToolResult.error_result(
                f"Unknown image kind: {params.kind}. "
                f"Use: hero, card, icon, logo, testimonial, svg, ai, openrouter"
            )

        # Write to file
        output_path = params.output_path
        if not output_path:
            ext = "png" if (params.kind == "ai" and svg.startswith("http")) else "svg"
            output_path = f"Output/images/{params.kind}_{uuid.uuid4().hex[:8]}.{ext}"

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if svg.startswith("http"):
            # Raster image URL — download it
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(svg) as resp:
                        if resp.status == 200:
                            path.write_bytes(await resp.read())
                        else:
                            return ToolResult.error_result(f"Failed to download image: HTTP {resp.status}")
            except ImportError:
                return ToolResult(
                    output=f"Image URL (install aiohttp to auto-download): {svg}",
                    data={"url": svg, "downloaded": False},
                )
        else:
            path.write_text(svg, encoding="utf-8")

        return ToolResult(
            output=f"Created {params.kind} image: {output_path} ({len(svg)} bytes)",
            data={
                "path": str(path.resolve()),
                "kind": params.kind,
                "size_bytes": len(svg),
                "format": path.suffix.lstrip("."),
            },
        )
