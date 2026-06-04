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


__all__ = ["LLMResponse"]
