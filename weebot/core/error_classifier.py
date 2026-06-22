"""ErrorClassifier — maps exceptions to recovery-routing categories.

Used by ResilientLLMAdapter to decide between:
  - retry (rate limit, network, model unavailable)
  - trigger compressor (context length exceeded)
  - fail fast (auth errors — no point retrying)
  - unknown (default retry behaviour preserved)
"""
from __future__ import annotations

import re
from enum import Enum
from typing import List, Tuple


__all__ = [
    "ErrorCategory",
    "RecoveryAction",
    "ErrorClassifier",
]


class ErrorCategory(Enum):
    """Granular error taxonomy for LLM API failures.

    Expanded from 7 to 11 categories to enable precise recovery routing.
    """
    RATE_LIMIT = "rate_limit"
    CONTEXT_LENGTH = "context_length"
    AUTH = "auth"
    MODEL_UNAVAILABLE = "model_unavailable"
    TOOL_ERROR = "tool_error"
    NETWORK = "network"
    CONTENT_FILTER = "content_filter"       # NEW: content policy violations
    BAD_REQUEST = "bad_request"             # NEW: malformed request (400)
    SERVER_ERROR = "server_error"           # NEW: provider-side 5xx (distinct from network)
    TIMEOUT = "timeout"                     # NEW: request timeout (distinct from network)
    UNKNOWN = "unknown"


class RecoveryAction(Enum):
    """Explicit action ladder — what to do with a classified error.

    Ordered by escalation level (least to most severe).
    """
    COMPRESS = "compress"                   # Trigger context compression, then retry
    RETRY = "retry"                        # Retry same model with backoff
    BACKOFF = "backoff"                    # Retry with longer backoff (rate limit)
    FALLBACK_MODEL = "fallback_model"       # Try a different model
    FAIL_FAST = "fail_fast"                # Don't retry, raise immediately
    ESCALATE = "escalate"                  # Don't retry, escalate to next handler


# ── Taxonomy: category → recovery action ────────────────────────────────────
# First-match-wins. Order matters: more specific patterns before generic ones.
_PATTERNS: List[Tuple[str, ErrorCategory]] = [
    # Context length — must be before generic model errors
    (r"context.{0,30}(length|window|limit|exceed|too.long)", ErrorCategory.CONTEXT_LENGTH),
    (r"maximum.{0,20}token", ErrorCategory.CONTEXT_LENGTH),
    (r"prompt.{0,20}too.{0,10}long", ErrorCategory.CONTEXT_LENGTH),
    # Rate limit
    (r"rate.?limit|too.many.request|429|quota.exceed", ErrorCategory.RATE_LIMIT),
    # Content filter — policy violations (won't succeed on retry)
    (r"content.?policy|safety.?policy|inappropriate|harmful.?content|"
     r"content.?filter|flagged|violat.+policy", ErrorCategory.CONTENT_FILTER),
    # Auth / billing — fail fast, no point retrying
    (r"api.?key|unauthorized|authentication|40[123]|invalid.?key|payment.?required", ErrorCategory.AUTH),
    # Bad request — malformed payload (won't succeed on retry)
    (r"bad.request|invalid.request|invalid.parameter|400", ErrorCategory.BAD_REQUEST),
    # Timeout — distinct from general network
    (r"(gateway|request|connection|read|write).?timeout|timed.?out", ErrorCategory.TIMEOUT),
    # Model unavailable
    (r"model.{0,20}(not.found|unavailable|deprecated|overloaded)|503", ErrorCategory.MODEL_UNAVAILABLE),
    # Server error — provider-side 5xx (distinct from network flakiness)
    (r"50[0-2]|50[4-9]|internal.server.error|server.error", ErrorCategory.SERVER_ERROR),
    # Network / transient (catch-all for remaining network issues)
    (r"connection|network|unreachable|502|504", ErrorCategory.NETWORK),
]


# ── Action ladder — category → recovery action ──────────────────────────────
_RECOMMENDED_ACTION: dict[ErrorCategory, RecoveryAction] = {
    ErrorCategory.CONTEXT_LENGTH:    RecoveryAction.COMPRESS,
    ErrorCategory.RATE_LIMIT:        RecoveryAction.BACKOFF,
    ErrorCategory.AUTH:              RecoveryAction.FAIL_FAST,
    ErrorCategory.MODEL_UNAVAILABLE: RecoveryAction.FALLBACK_MODEL,
    ErrorCategory.TOOL_ERROR:        RecoveryAction.ESCALATE,
    ErrorCategory.NETWORK:           RecoveryAction.RETRY,
    ErrorCategory.CONTENT_FILTER:    RecoveryAction.ESCALATE,
    ErrorCategory.BAD_REQUEST:       RecoveryAction.FAIL_FAST,
    ErrorCategory.SERVER_ERROR:      RecoveryAction.RETRY,
    ErrorCategory.TIMEOUT:           RecoveryAction.RETRY,
    ErrorCategory.UNKNOWN:           RecoveryAction.RETRY,
}


class ErrorClassifier:
    """Classify exceptions into ErrorCategory for routing decisions.

    Patterns are checked in order; first match wins. The combined string
    is ``f"{type(exc).__name__} {str(exc)}".lower()`` so both the
    exception class name and message are matched.
    """

    @classmethod
    def classify(cls, exc: BaseException) -> ErrorCategory:
        """Return the ErrorCategory for *exc*."""
        combined = f"{type(exc).__name__} {str(exc)}".lower()
        for pattern, category in _PATTERNS:
            if re.search(pattern, combined):
                return category
        return ErrorCategory.UNKNOWN

    @classmethod
    def recommend_action(cls, exc: BaseException) -> RecoveryAction:
        """Return the recommended RecoveryAction for *exc*."""
        category = cls.classify(exc)
        return _RECOMMENDED_ACTION.get(category, RecoveryAction.RETRY)

    @classmethod
    def should_compact(cls, exc: BaseException) -> bool:
        """True when the error warrants triggering a ConversationCompressor."""
        return cls.recommend_action(exc) == RecoveryAction.COMPRESS

    @classmethod
    def should_fail_fast(cls, exc: BaseException) -> bool:
        """True when retrying is pointless (auth errors, bad requests)."""
        return cls.recommend_action(exc) == RecoveryAction.FAIL_FAST

    @classmethod
    def should_fallback_model(cls, exc: BaseException) -> bool:
        """True when a different model should be tried."""
        return cls.recommend_action(exc) == RecoveryAction.FALLBACK_MODEL

    @classmethod
    def is_retryable(cls, exc: BaseException) -> bool:
        """True when the error can be retried (not fail-fast or escalate)."""
        action = cls.recommend_action(exc)
        return action in (RecoveryAction.RETRY, RecoveryAction.BACKOFF,
                          RecoveryAction.COMPRESS, RecoveryAction.FALLBACK_MODEL)

    @classmethod
    def is_path_error(cls, error_text: str) -> bool:
        """Return True if *error_text* is a filesystem path/exploration error.

        These are normal during exploratory steps — the executor is probing
        for file locations and some paths won't exist.  They should NOT count
        toward the cross-step failure threshold.
        """
        combined = error_text.lower()
        path_patterns = [
            r"cannot find path",
            r"does not exist",
            r"access to the path.*is denied",
            r"cannot find.*because it does",
            r"get-childitem.*cannot find",
            r"no such file or directory",
        ]
        for pattern in path_patterns:
            if re.search(pattern, combined):
                return True
        return False

    @classmethod
    def classify(cls, exc: BaseException) -> ErrorCategory:
        """Return the ErrorCategory for *exc*."""
        combined = f"{type(exc).__name__} {str(exc)}".lower()
        for pattern, category in _PATTERNS:
            if re.search(pattern, combined):
                return category
        return ErrorCategory.UNKNOWN

    @classmethod
    def should_compact(cls, exc: BaseException) -> bool:
        """True when the error warrants triggering a ConversationCompressor."""
        return cls.classify(exc) == ErrorCategory.CONTEXT_LENGTH

    @classmethod
    def should_fail_fast(cls, exc: BaseException) -> bool:
        """True when retrying is pointless (auth errors)."""
        return cls.classify(exc) == ErrorCategory.AUTH

    @classmethod
    def is_path_error(cls, error_text: str) -> bool:
        """Return True if *error_text* is a filesystem path/exploration error.

        These are normal during exploratory steps — the executor is probing
        for file locations and some paths won't exist.  They should NOT count
        toward the cross-step failure threshold.
        """
        combined = error_text.lower()
        path_patterns = [
            r"cannot find path",
            r"does not exist",
            r"access to the path.*is denied",
            r"cannot find.*because it does",
            r"get-childitem.*cannot find",
            r"no such file or directory",
        ]
        for pattern in path_patterns:
            if re.search(pattern, combined):
                return True
        return False

    @classmethod
    def should_fallback_model(cls, exc: BaseException) -> bool:
        """True when a different model should be tried."""
        return cls.recommend_action(exc) == RecoveryAction.FALLBACK_MODEL
