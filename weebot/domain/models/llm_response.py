"""LLM response model — domain value object.

Extracted from weebot/application/ports/llm_port.py during architecture
remediation (step-9) to keep application ports pure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LLMResponse:
    """Normalized LLM response regardless of provider."""
    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    model: str = "unknown"
    usage: Dict[str, int] = field(default_factory=dict)


@dataclass
class LLMChunk:
    """One increment of a streamed LLM response.

    Mirrors ``LLMResponse`` but for a single delta rather than the full
    completion. ``tool_call_deltas`` carries partial tool-call JSON
    fragments in the OpenAI streaming shape (index/id/function.arguments
    pieces) — callers accumulate these across chunks the same way the
    OpenAI SDK's own streaming helper does; weebot does not re-parse them
    here so adapters stay a thin passthrough.
    """
    delta: str = ""
    tool_call_deltas: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None
    model: str = "unknown"
    usage: Optional[Dict[str, int]] = None


__all__ = ["LLMResponse", "LLMChunk"]
