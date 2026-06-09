"""Credential sanitizer — masks passwords, tokens, and API keys in user text.

This module provides a pure-function sanitizer that runs BEFORE any
user-provided text is persisted to session storage, event bus, logs,
or the behavior ledger. It prevents PII leaks like the LinkedIn
password bug where ``ask_human`` responses were stored in plaintext.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ── Patterns adapted from weebot/infrastructure/adapters/llm/resilient_adapter.py
#    and weebot/infrastructure/security/agent_sanitizer.py ──────────────

_CREDENTIAL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # password=value / password: value / passwd=value
    (re.compile(r'(password|passwd|pwd|secret)\s*([=:])\s*\S+', re.IGNORECASE),
     r'\1\2***REDACTED***'),
    # API keys: key=sk-... / api_key=abc123...
    (re.compile(r'(api[_-]?key|apikey|token)\s*[=:]\s*\S+', re.IGNORECASE),
     r'\1=***REDACTED***'),
    # OpenAI / Anthropic key patterns (sk-..., sk-ant-...)
    (re.compile(r'(sk-[a-zA-Z0-9_-]{20,})'),
     '***REDACTED-API-KEY***'),
    # Colon-separated password only (no =, already handled above)
    (re.compile(r'password\s*:\s*\S+', re.IGNORECASE),
     'password: ***REDACTED***'),
    # JWT tokens (eyJ...)
    (re.compile(r'eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}'),
     '***REDACTED-JWT***'),
    # AWS-style keys (AKIA..., ASIA...)
    (re.compile(r'\b(AKIA|ASIA)[A-Z0-9]{16}\b'),
     '***REDACTED-AWS-KEY***'),
]


def sanitize(text: str) -> str:
    """Apply all credential-redaction patterns to *text*.

    Returns the sanitized string.  If no patterns match, the original
    string is returned unchanged.
    """
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def has_credentials(text: str) -> bool:
    """Return True if *text* appears to contain credentials."""
    for pattern, _replacement in _CREDENTIAL_PATTERNS:
        if pattern.search(text):
            return True
    return False
