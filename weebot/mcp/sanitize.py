"""Resource sanitization helpers for the weebot MCP server.

These functions strip common prompt-injection patterns from text before it is
returned in an MCP resource response.  They are pure presentation-layer filters;
they do NOT modify any underlying data store.
"""
from __future__ import annotations

import re
from typing import Any

_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+previous\s+instructions?"),
    re.compile(r"(?i)disregard\s+(the\s+)?above"),
    re.compile(r"(?i)system\s+prompt[:\s]*"),
    re.compile(r"(?i)you\s+are\s+now\s+.*"),
    re.compile(r"(?i)⟦END_UNTRUSTED_DATA⟧"),  # delimiter injection
    re.compile(r"(?i)⟦UNTRUSTED_DATA\b"),
]


def sanitize(text: str) -> str:
    """Strip common prompt-injection patterns from resource text.

    Returns the text with injection phrases replaced by ``[REDACTED]``.
    Non-string inputs are returned unchanged so the function can be safely
    applied inside recursive JSON traversal.
    """
    if not isinstance(text, str):
        return text
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def sanitize_json_fields(obj: Any) -> Any:
    """Recursively sanitize all string values in a JSON-compatible structure."""
    if isinstance(obj, dict):
        return {k: sanitize_json_fields(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json_fields(v) for v in obj]
    if isinstance(obj, str):
        return sanitize(obj)
    return obj
