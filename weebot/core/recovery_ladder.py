"""Recovery ladder: which rung to try next after a classified LLM failure (H3).

Policy only. ``plan_recovery`` is a pure function over a category and what has already been
tried; the executor (``executor/_recovery.py``) performs the rung. Each rung is tried at most
once per call, so the ladder always ends.
"""

from __future__ import annotations

from dataclasses import dataclass

from weebot.core.error_classifier import ErrorCategory, RecoveryAction

__all__ = [
    "Rung",
    "RecoveryAttempt",
    "LADDERS",
    "RECOVERABLE",
    "plan_recovery",
    "failure_message",
]

# A Retry-After at or below this is worth waiting out on the same model.
SHORT_RETRY_AFTER_S = 5.0


@dataclass(frozen=True, slots=True)
class Rung:
    action: RecoveryAction
    # COMPRESS only: also prune every old tool output first (the aggressive rung).
    aggressive: bool = False


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    rungs_used: frozenset[Rung] = frozenset()
    retry_after: float | None = None


_COMPRESS = Rung(RecoveryAction.COMPRESS)
_COMPRESS_HARD = Rung(RecoveryAction.COMPRESS, aggressive=True)
_BACKOFF = Rung(RecoveryAction.BACKOFF)
_FALLBACK = Rung(RecoveryAction.FALLBACK_MODEL)

# Category -> rungs in order. A category with no entry has no ladder and is re-raised.
LADDERS: dict[ErrorCategory, tuple[Rung, ...]] = {
    ErrorCategory.CONTEXT_LENGTH: (
        _COMPRESS,
        _COMPRESS_HARD,
        Rung(RecoveryAction.LARGER_CONTEXT_MODEL),
    ),
    ErrorCategory.PAYLOAD_TOO_LARGE: (
        _COMPRESS,
        _COMPRESS_HARD,
        Rung(RecoveryAction.LARGER_CONTEXT_MODEL),
    ),
    ErrorCategory.MULTIMODAL_UNSUPPORTED: (Rung(RecoveryAction.STRIP_MEDIA), _FALLBACK),
    ErrorCategory.RATE_LIMIT_UPSTREAM: (_BACKOFF, _FALLBACK),
    ErrorCategory.TOOL_SCHEMA_REJECTED: (_FALLBACK,),
    # Key- or account-level: another model on the same key will not help.
    ErrorCategory.QUOTA_EXHAUSTED: (),
    ErrorCategory.AUTH: (),
}

RECOVERABLE = frozenset(c for c, rungs in LADDERS.items() if rungs)


def plan_recovery(category: ErrorCategory, attempt: RecoveryAttempt) -> Rung | None:
    """The next untried rung for *category*, or None when the ladder is spent or absent."""
    for rung in LADDERS.get(category, ()):
        if rung in attempt.rungs_used:
            continue
        if (
            rung.action is RecoveryAction.BACKOFF
            and attempt.retry_after is not None
            and attempt.retry_after > SHORT_RETRY_AFTER_S
        ):
            continue  # waiting that long is worse than moving to another model
        return rung
    return None


_MESSAGES: dict[ErrorCategory, str] = {
    ErrorCategory.CONTEXT_LENGTH: (
        "The conversation no longer fits any available model's context window, even after "
        "compressing it. Start a new session or ask for a shorter task."
    ),
    ErrorCategory.PAYLOAD_TOO_LARGE: (
        "The request body is too large for the provider, even after compressing it. "
        "Remove large attachments or screenshots and retry."
    ),
    ErrorCategory.MULTIMODAL_UNSUPPORTED: (
        "The selected models cannot read images, and removing them did not help."
    ),
    ErrorCategory.RATE_LIMIT_UPSTREAM: (
        "The providers behind your router are rate-limiting right now. Wait a minute and retry."
    ),
    ErrorCategory.QUOTA_EXHAUSTED: (
        "Your provider account is out of credit or quota. Top it up (for OpenRouter: "
        "https://openrouter.ai/credits); trying other models on the same key will not help."
    ),
    ErrorCategory.TOOL_SCHEMA_REJECTED: (
        "The provider rejected the tool definitions for every model tried."
    ),
}

_GENERIC = (
    "All AI models are currently unavailable. Please:\n"
    "1. Check your OpenRouter credits at https://openrouter.ai/credits\n"
    "2. Verify your OPENROUTER_API_KEY is valid\n"
    "3. Wait a few minutes for circuit breakers to cool down and retry"
)


def failure_message(category: ErrorCategory | None) -> str:
    """What to tell the user when the cascade is spent, specific to *category* when known."""
    return _MESSAGES.get(category, _GENERIC) if category else _GENERIC
