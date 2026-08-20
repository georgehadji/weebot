"""LLM port — abstract interface for language model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMPort(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return the response."""
        ...

    async def build_multimodal_message(
        self, role: str, text: str, image_base64: str, media_type: str = "image/png"
    ) -> dict[str, Any]:
        """Build a provider-neutral multimodal message dict carrying one image.

        Implementations may override for provider-specific shaping; the default
        returns a dict with ``role`` and ``content`` as a list of text + image
        blocks that the adapter layer converts per-provider via ``convert_messages``.

        Args:
            role: Message role (typically ``"user"``).
            text: Caption shown before the image (omitted from content if empty).
            image_base64: Base64-encoded image payload (no data-URL prefix).
            media_type: MIME type, e.g. ``image/png``.

        Returns:
            A provider-neutral multimodal message dict.
        """
        content: list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({"type": "image", "data": image_base64, "media_type": media_type})
        return {"role": role, "content": content}


from weebot.domain.models.llm_response import LLMResponse
