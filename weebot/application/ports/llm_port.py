"""LLM port — abstract interface for language model providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLMPort(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> "LLMResponse":
        """Send a chat completion request and return the response."""
        ...


class LLMResponse:
    """Normalized LLM response regardless of provider."""

    def __init__(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
    ):
        self.content = content or ""
        self.tool_calls = tool_calls or []
        self.model = model or "unknown"
        self.usage = usage or {}
