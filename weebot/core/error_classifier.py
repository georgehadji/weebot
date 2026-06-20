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


__all__ = ["ErrorClassifier", "ErrorCategory"]


class ErrorCategory(Enum):
    RATE_LIMIT = "rate_limit"
    CONTEXT_LENGTH = "context_length"
    AUTH = "auth"
    MODEL_UNAVAILABLE = "model_unavailable"
    TOOL_ERROR = "tool_error"
    NETWORK = "network"
    UNKNOWN = "unknown"


class ErrorClassifier:
    """Classify exceptions into ErrorCategory for routing decisions.

    Patterns are checked in order; first match wins. The combined string
    is ``f"{type(exc).__name__} {str(exc)}".lower()`` so both the
    exception class name and message are matched.
    """

    # (regex_pattern, category) — checked in order, first match wins
    _PATTERNS: list[tuple[str, ErrorCategory]] = [
        # Context length — must be before generic model errors
        (r"context.{0,30}(length|window|limit|exceed|too.long)", ErrorCategory.CONTEXT_LENGTH),
        (r"maximum.{0,20}token", ErrorCategory.CONTEXT_LENGTH),
        (r"prompt.{0,20}too.{0,10}long", ErrorCategory.CONTEXT_LENGTH),
        # Rate limit
        (r"rate.?limit|too.many.request|429|quota.exceed", ErrorCategory.RATE_LIMIT),
        # Auth / billing — fail fast, no point retrying
        (r"api.?key|unauthorized|authentication|40[123]|invalid.?key|payment.?required", ErrorCategory.AUTH),
        # Model unavailable
        (r"model.{0,20}(not.found|unavailable|deprecated|overloaded)|503", ErrorCategory.MODEL_UNAVAILABLE),
        # Network / transient
        (r"connection|timeout|network|unreachable|502|504", ErrorCategory.NETWORK),
    ]

    @classmethod
    def classify(cls, exc: BaseException) -> ErrorCategory:
        """Return the ErrorCategory for *exc*."""
        combined = f"{type(exc).__name__} {str(exc)}".lower()
        for pattern, category in cls._PATTERNS:
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
    def should_fallback_model(cls, exc: BaseException) -> bool:
        """True when a different model should be tried."""
        return cls.classify(exc) in (ErrorCategory.RATE_LIMIT, ErrorCategory.MODEL_UNAVAILABLE)
