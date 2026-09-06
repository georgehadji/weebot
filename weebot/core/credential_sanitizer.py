"""Credential sanitizer — masks passwords, tokens, and API keys in user text.

This module provides a pure-function sanitizer that runs BEFORE any
user-provided text is persisted to session storage, event bus, logs,
or the behavior ledger. It prevents PII leaks like the LinkedIn
password bug where ``ask_human`` responses were stored in plaintext.
"""

from __future__ import annotations

import re
from typing import Any

# ── Patterns adapted from weebot/infrastructure/adapters/llm/resilient_adapter.py
#    and weebot/infrastructure/security/agent_sanitizer.py ──────────────

_CREDENTIAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # password=value / password: value / passwd=value
    (
        re.compile(r"(password|passwd|pwd|secret)\s*([=:])\s*\S+", re.IGNORECASE),
        r"\1\2***REDACTED***",
    ),
    # API keys: key=sk-... / api_key=abc123...
    (re.compile(r"(api[_-]?key|apikey|token)\s*[=:]\s*\S+", re.IGNORECASE), r"\1=***REDACTED***"),
    # OpenAI / Anthropic key patterns (sk-..., sk-ant-...)
    (re.compile(r"(sk-[a-zA-Z0-9_-]{20,})"), "***REDACTED-API-KEY***"),
    # Colon-separated password only (no =, already handled above)
    (re.compile(r"password\s*:\s*\S+", re.IGNORECASE), "password: ***REDACTED***"),
    # JWT tokens (eyJ...). The per-segment minimum used to be 20, which made
    # redaction depend on the header's length rather than on it being a JWT:
    # `{"alg":"HS256"}` encodes to 17 characters after `eyJ` and leaked, while
    # `{"alg":"HS256","typ":"JWT"}` reached 33 and was caught. Both are
    # ordinary headers. The `eyJ` prefix plus three base64url segments is the
    # specificity; the length was never doing that work.
    (
        re.compile(r"eyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}"),
        "***REDACTED-JWT***",
    ),
    # AWS-style keys (AKIA..., ASIA...)
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "***REDACTED-AWS-KEY***"),
    # Authorization headers. `Bearer <jwt>` is already covered above, but a
    # bearer token that is not a JWT, and Basic's base64 user:password, were
    # not — both leaked verbatim through `sanitize()`.
    (
        re.compile(r"(Authorization\s*:\s*)(Bearer|Basic|Token)\s+\S+", re.IGNORECASE),
        r"\1\2 ***REDACTED***",
    ),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-~+/]{16,}=*"), "Bearer ***REDACTED***"),
    # GitHub personal-access / OAuth / server / refresh tokens.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"), "***REDACTED-GITHUB-TOKEN***"),
    # Google API keys.
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b"), "***REDACTED-GOOGLE-KEY***"),
    # Slack bot / user / app / refresh tokens and webhook URLs.
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "***REDACTED-SLACK-TOKEN***"),
    (
        re.compile(r"https://hooks\.slack\.com/services/\S+"),
        "***REDACTED-SLACK-WEBHOOK***",
    ),
    # Credentials embedded in a URL: scheme://user:password@host
    (
        re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+):([^\s@]+)@"),
        r"\1:***REDACTED***@",
    ),
]

# Event fields that carry free text a credential can appear in. `ToolEvent.result`
# is the one that matters most: it is raw stdout, so `cat .env`, `env` and
# `git remote -v` all land there, and until this existed it reached the event
# bus, the WebSocket broadcast and SQLite untouched.
_SANITISED_EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "message": ("message",),
    "tool": ("result",),
    "error": ("error",),
    "step": ("description",),
    "thought": ("thought", "message", "content"),
    "wait_for_user": ("question",),
    "title": ("title",),
}


def sanitize(text: str) -> str:
    """Apply all credential-redaction patterns to *text*.

    Returns the sanitized string.  If no patterns match, the original
    string is returned unchanged.
    """
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_event(event: Any) -> Any:
    """Redact credentials from every free-text field an event carries.

    The three emit pipelines each gated this on
    ``isinstance(event, MessageEvent) and event.role == "user"``, so a
    credential was scrubbed only when the human typed it. Everything the agent
    *produced* went out raw — above all ``ToolEvent.result``, which is tool
    stdout, and therefore the output of `cat .env`, `env` or `git remote -v`.
    That reached the event bus, the WebSocket broadcast to the web UI and
    SQLite, while `EventPublisher`'s own docstring listed credential
    sanitisation as an unconditional stage.

    Returns the event unchanged when nothing matched, so callers can use
    identity to decide whether to log a redaction.
    """
    fields = _SANITISED_EVENT_FIELDS.get(getattr(event, "type", ""), ())
    updates: dict[str, str] = {}
    for name in fields:
        value = getattr(event, name, None)
        if isinstance(value, str) and value:
            cleaned = sanitize(value)
            if cleaned != value:
                updates[name] = cleaned
    if not updates:
        return event
    return event.model_copy(update=updates)


def has_credentials(text: str) -> bool:
    """Return True if *text* appears to contain credentials."""
    for pattern, _replacement in _CREDENTIAL_PATTERNS:
        if pattern.search(text):
            return True
    return False
