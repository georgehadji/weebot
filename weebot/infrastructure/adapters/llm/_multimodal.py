"""Provider-neutral multimodal message helpers.

The executor builds provider-neutral messages whose ``content`` is a list of
blocks instead of a plain string:

    {"type": "text",  "text": "..."}
    {"type": "image", "data": "<base64>", "media_type": "image/png"}

Each LLM adapter calls :func:`convert_messages` to map those blocks to its
provider's wire format. Messages whose ``content`` is a plain string (today's
overwhelming common case) pass through untouched, so wiring this in is purely
additive and low-risk.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal

Provider = Literal["anthropic", "openai"]

DEFAULT_MEDIA_TYPE = "image/png"

# Substrings identifying vision-capable model families. A false negative only
# skips screenshot injection (safe); a false positive would send an image to a
# model that may reject it, so keep this list conservative.
_VISION_MODEL_MARKERS = (
    "claude-3",
    "claude-opus",
    "claude-sonnet",
    "claude-haiku",
    "claude-fable",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4-vision",
    "gpt-5",
    "o1",
    "o3",
    "gemini",
    "llava",
    "pixtral",
    "qwen2-vl",
    "qwen2.5-vl",
)


def model_supports_vision(model: str) -> bool:
    """Best-effort check whether *model* accepts image input.

    Conservative substring match over known vision-capable families. Unknown
    or text-only models return False, so screenshot injection is skipped safely.
    """
    m = (model or "").lower()
    return any(marker in m for marker in _VISION_MODEL_MARKERS)


def build_image_message(
    text: str,
    base64_image: str,
    media_type: str = DEFAULT_MEDIA_TYPE,
    role: str = "user",
) -> Dict[str, Any]:
    """Build a provider-neutral multimodal message carrying one screenshot.

    Args:
        text: Optional caption shown before the image (omitted if empty).
        base64_image: Base64-encoded image payload (no data-URL prefix).
        media_type: MIME type, e.g. ``image/png``.
        role: Message role (default ``user``).

    Returns:
        A neutral message dict; convert it per-provider via :func:`convert_messages`.
    """
    content: List[Dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.append({"type": "image", "data": base64_image, "media_type": media_type})
    return {"role": role, "content": content}


def convert_messages(
    messages: List[Dict[str, Any]], target: Provider
) -> List[Dict[str, Any]]:
    """Return a new message list with neutral image blocks mapped to *target* format.

    Messages whose ``content`` is not a list are returned unchanged. The input
    list and its dicts are never mutated.
    """
    out: List[Dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue
        out.append({**msg, "content": _convert_blocks(content, target)})
    return out


def _convert_blocks(
    blocks: List[Any], target: Provider
) -> List[Dict[str, Any]]:
    """Map a list of neutral content blocks to provider format (total — never raises)."""
    converted: List[Dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            converted.append({"type": "text", "text": str(block)})
            continue
        btype = block.get("type")
        if btype == "text":
            converted.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            converted.append(_image_block(block, target))
        else:
            # Unknown block type — degrade to text rather than send an invalid
            # payload that the provider would reject.
            converted.append(
                {"type": "text", "text": f"[unsupported content block: {btype}]"}
            )
    return converted


def _image_block(block: Dict[str, Any], target: Provider) -> Dict[str, Any]:
    """Map a neutral image block to the provider's image content shape."""
    data = block.get("data", "")
    media_type = block.get("media_type", DEFAULT_MEDIA_TYPE)
    if target == "anthropic":
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    # OpenAI-compatible: inline data URL.
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{data}"},
    }
