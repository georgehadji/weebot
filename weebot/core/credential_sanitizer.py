"""Credential sanitizer — masks passwords, tokens, and API keys in user text.

This module provides a pure-function sanitizer that runs BEFORE any
user-provided text is persisted to session storage, event bus, logs,
or the behavior ledger. It prevents PII leaks like the LinkedIn
password bug where ``ask_human`` responses were stored in plaintext.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

# ── Patterns adapted from weebot/infrastructure/adapters/llm/resilient_adapter.py
#    and weebot/infrastructure/security/agent_sanitizer.py ──────────────

logger = logging.getLogger(__name__)

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
    #
    # The username part is `*`, not `+`. It was `+`, which requires a non-empty
    # user — and Redis, AMQP and several others put the password in with NO
    # username: `rediss://:s3cr3tpassword@cache.internal:6379/0` matched
    # nothing and logged in full.
    (
        re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]*):([^\s@]+)@"),
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


@lru_cache(maxsize=1)
def _secret_redactor() -> Any:
    """The `SecretRedactor` singleton, built lazily.

    Lazy because `SecretRedactor.from_settings()` constructs `WeebotSettings`,
    and this module is imported from three emit pipelines that must not pay for
    settings resolution at import time.

    `lru_cache` rather than a module global: `test_core_no_global_singletons_outside_di`
    bans `global` in `core/`, and it is right to — a cached function has the
    same one-instance behaviour, is clearable in a test via `.cache_clear()`,
    and cannot be reassigned from anywhere else.
    """
    from weebot.core.secret_redaction import SecretRedactor

    return SecretRedactor.from_settings()


def sanitize(text: str) -> str:
    """Apply all credential-redaction patterns to *text*.

    Returns the sanitized string.  If no patterns match, the original
    string is returned unchanged.

    Runs `SecretRedactor`'s pattern passes after this module's own. That class
    is 184 lines that had **zero callers** while `settings.py` declared
    `secret_redaction_enabled: bool = True`, described as redacting secrets "in
    tool output and logs" — a configuration reporting a control that had never
    run. What it adds here is not duplication: Luhn-checked card numbers,
    Stripe keys and labelled CVVs, none of which the denylist above covers.

    Its ENTROPY pass stays off, and that is the measured reason rather than
    caution. On this codebase's own tool output it redacts commit SHAs, session
    UUIDs, sha256 digests and **file paths** — see `SecretRedactor.from_settings`.
    Wiring it before that was understood would have shipped a log-corruption
    bug on the same commit as a security fix.
    """
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    try:
        return _secret_redactor().redact(text)
    except Exception:
        # A sanitiser that raises is a sanitiser that gets removed. The
        # denylist result above is already applied, so the fallback still
        # redacts; it just loses the PAN and Stripe passes.
        logger.debug("SecretRedactor pass failed; returning the denylist result.", exc_info=True)
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
