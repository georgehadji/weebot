"""Tests for ErrorClassifier — expanded taxonomy + RecoveryAction ladder."""
from __future__ import annotations

import pytest

from weebot.core.error_classifier import (
    ErrorClassifier,
    ErrorCategory,
    RecoveryAction,
    _PATTERNS,
    _RECOMMENDED_ACTION,
)


# ── RecoveryAction ladder ────────────────────────────────────────────────────

class TestRecoveryActionLadder:
    """Every ErrorCategory must have a mapped RecoveryAction."""

    def test_all_categories_have_recovery_action(self):
        """Every category in the enum must have an entry in the action ladder."""
        for category in ErrorCategory:
            assert category in _RECOMMENDED_ACTION, (
                f"ErrorCategory.{category.name} has no RecoveryAction mapping"
            )

    def test_all_recovery_actions_used(self):
        """Every RecoveryAction value must be mapped to at least one category."""
        used = set(_RECOMMENDED_ACTION.values())
        for action in RecoveryAction:
            assert action in used, (
                f"RecoveryAction.{action.name} is not used by any category"
            )

    def test_is_retryable_includes_retry_and_backoff(self):
        """BACKOFF and RETRY actions are retryable."""
        assert RecoveryAction.RETRY in (RecoveryAction.RETRY, RecoveryAction.BACKOFF,
                                         RecoveryAction.COMPRESS, RecoveryAction.FALLBACK_MODEL)
        assert RecoveryAction.BACKOFF in (RecoveryAction.RETRY, RecoveryAction.BACKOFF,
                                           RecoveryAction.COMPRESS, RecoveryAction.FALLBACK_MODEL)
        assert RecoveryAction.COMPRESS in (RecoveryAction.RETRY, RecoveryAction.BACKOFF,
                                            RecoveryAction.COMPRESS, RecoveryAction.FALLBACK_MODEL)
        assert RecoveryAction.FALLBACK_MODEL in (RecoveryAction.RETRY, RecoveryAction.BACKOFF,
                                                  RecoveryAction.COMPRESS, RecoveryAction.FALLBACK_MODEL)

    def test_is_retryable_excludes_fail_fast_and_escalate(self):
        """FAIL_FAST and ESCALATE actions are NOT retryable."""
        assert RecoveryAction.FAIL_FAST not in (RecoveryAction.RETRY, RecoveryAction.BACKOFF,
                                                 RecoveryAction.COMPRESS, RecoveryAction.FALLBACK_MODEL)
        assert RecoveryAction.ESCALATE not in (RecoveryAction.RETRY, RecoveryAction.BACKOFF,
                                                RecoveryAction.COMPRESS, RecoveryAction.FALLBACK_MODEL)


# ── Existing category regression tests ───────────────────────────────────────

class TestCategoryRegression:
    """Existing error patterns must still classify correctly."""

    def test_401_is_auth(self):
        assert ErrorClassifier.classify(Exception("401 Unauthorized")) == ErrorCategory.AUTH
        assert ErrorClassifier.recommend_action(Exception("401 Unauthorized")) == RecoveryAction.FAIL_FAST

    def test_402_is_auth(self):
        assert ErrorClassifier.classify(Exception("402 Payment Required")) == ErrorCategory.AUTH
        assert ErrorClassifier.should_fail_fast(Exception("402 Payment Required")) is True

    def test_403_is_auth(self):
        assert ErrorClassifier.classify(Exception("403 Forbidden")) == ErrorCategory.AUTH

    def test_429_is_rate_limit(self):
        assert ErrorClassifier.classify(Exception("429 Too Many Requests")) == ErrorCategory.RATE_LIMIT
        # Rate limits now produce BACKOFF action (not FALLBACK_MODEL) — backoff is separate from model fallback
        assert ErrorClassifier.is_retryable(Exception("429 Too Many Requests")) is True

    def test_503_is_model_unavailable(self):
        assert ErrorClassifier.classify(Exception("503 Service Unavailable")) == ErrorCategory.MODEL_UNAVAILABLE

    def test_context_length(self):
        assert ErrorClassifier.classify(Exception("context length exceeded")) == ErrorCategory.CONTEXT_LENGTH
        assert ErrorClassifier.should_compact(Exception("context length exceeded")) is True

    def test_rate_limit_keyword(self):
        assert ErrorClassifier.classify(Exception("rate limit exceeded")) == ErrorCategory.RATE_LIMIT

    def test_api_key_invalid_is_auth(self):
        assert ErrorClassifier.classify(Exception("invalid api key")) == ErrorCategory.AUTH

    def test_path_errors_still_detected(self):
        assert ErrorClassifier.is_path_error("Cannot find path 'X' because it does not exist") is True
        assert ErrorClassifier.is_path_error("No such file or directory: /tmp/missing") is True
        assert ErrorClassifier.is_path_error("TypeError: 'NoneType' has no attribute 'x'") is False


# ── New category tests ───────────────────────────────────────────────────────

class TestCategoryContentFilter:
    def test_content_policy_violation(self):
        exc = Exception("Content policy violation: inappropriate content detected")
        assert ErrorClassifier.classify(exc) == ErrorCategory.CONTENT_FILTER
        assert ErrorClassifier.should_fail_fast(exc) is False  # not AUTH
        assert ErrorClassifier.is_retryable(exc) is False      # won't succeed on retry

    def test_safety_policy(self):
        assert ErrorClassifier.classify(Exception("safety policy triggered")) == ErrorCategory.CONTENT_FILTER

    def test_flagged_content(self):
        assert ErrorClassifier.classify(Exception("flagged for harmful content")) == ErrorCategory.CONTENT_FILTER

    def test_content_filter_action(self):
        assert ErrorClassifier.recommend_action(Exception("content filter")) == RecoveryAction.ESCALATE


class TestCategoryBadRequest:
    def test_bad_request(self):
        exc = Exception("400 Bad Request: invalid parameter 'model'")
        assert ErrorClassifier.classify(exc) == ErrorCategory.BAD_REQUEST
        assert ErrorClassifier.is_retryable(exc) is False

    def test_invalid_request(self):
        assert ErrorClassifier.classify(Exception("invalid request payload")) == ErrorCategory.BAD_REQUEST

    def test_invalid_parameter(self):
        assert ErrorClassifier.classify(Exception("invalid parameter: temperature")) == ErrorCategory.BAD_REQUEST

    def test_bad_request_action(self):
        assert ErrorClassifier.recommend_action(Exception("bad request")) == RecoveryAction.FAIL_FAST


class TestCategoryTimeout:
    def test_gateway_timeout(self):
        exc = Exception("Gateway timeout")
        assert ErrorClassifier.classify(exc) == ErrorCategory.TIMEOUT
        assert ErrorClassifier.is_retryable(exc) is True

    def test_request_timeout(self):
        assert ErrorClassifier.classify(Exception("Request timed out")) == ErrorCategory.TIMEOUT

    def test_connection_timeout(self):
        assert ErrorClassifier.classify(Exception("Connection timeout after 30s")) == ErrorCategory.TIMEOUT

    def test_timeout_action(self):
        assert ErrorClassifier.recommend_action(Exception("timed out")) == RecoveryAction.RETRY


class TestCategoryServerError:
    def test_500_server_error(self):
        exc = Exception("500 Internal Server Error")
        assert ErrorClassifier.classify(exc) == ErrorCategory.SERVER_ERROR
        assert ErrorClassifier.is_retryable(exc) is True
        assert ErrorClassifier.should_fail_fast(exc) is False

    def test_501_not_implemented(self):
        assert ErrorClassifier.classify(Exception("501 Not Implemented")) == ErrorCategory.SERVER_ERROR

    def test_502_bad_gateway(self):
        assert ErrorClassifier.classify(Exception("502 Bad Gateway")) == ErrorCategory.SERVER_ERROR

    def test_504_gateway_timeout(self):
        """504 Gateway Timeout maps to TIMEOUT (matches 'gateway timeout' before 5xx)."""
        assert ErrorClassifier.classify(Exception("504 Gateway Timeout")) == ErrorCategory.TIMEOUT

    def test_internal_server_error_text(self):
        assert ErrorClassifier.classify(Exception("Internal server error")) == ErrorCategory.SERVER_ERROR

    def test_server_error_action(self):
        assert ErrorClassifier.recommend_action(Exception("server error")) == RecoveryAction.RETRY

    def test_503_still_model_unavailable(self):
        """503 should remain MODEL_UNAVAILABLE (not SERVER_ERROR)."""
        assert ErrorClassifier.classify(Exception("503 Service Unavailable")) == ErrorCategory.MODEL_UNAVAILABLE


# ── recommend_action integration ────────────────────────────────────────────

class TestRecommendAction:
    """recommend_action must produce the correct RecoveryAction for each category."""

    def test_recommend_action_for_each_category(self):
        cases = [
            ("context length exceeded", RecoveryAction.COMPRESS),
            ("rate limit exceeded", RecoveryAction.BACKOFF),
            ("401 Unauthorized", RecoveryAction.FAIL_FAST),
            ("400 Bad Request", RecoveryAction.FAIL_FAST),
            ("model not found", RecoveryAction.FALLBACK_MODEL),
            ("503 Service Unavailable", RecoveryAction.FALLBACK_MODEL),
            ("connection refused", RecoveryAction.RETRY),
            ("content policy violation", RecoveryAction.ESCALATE),
            ("500 Internal Server Error", RecoveryAction.RETRY),
            ("Request timed out", RecoveryAction.RETRY),
            ("completely unknown error", RecoveryAction.RETRY),
        ]
        for message, expected_action in cases:
            exc = Exception(message)
            action = ErrorClassifier.recommend_action(exc)
            assert action == expected_action, (
                f"recommend_action({message!r}) = {action}, expected {expected_action}"
            )

    def test_should_fallback_model_new_behavior(self):
        """should_fallback_model should only be True for FALLBACK_MODEL actions."""
        # RATE_LIMIT → BACKOFF (not FALLBACK_MODEL) — backoff is separate from model fallback
        assert ErrorClassifier.should_fallback_model(Exception("rate limit")) is False
        # MODEL_UNAVAILABLE → FALLBACK_MODEL
        assert ErrorClassifier.should_fallback_model(Exception("model not found")) is True

    def test_is_retryable_integration(self):
        """is_retryable integrates with recommend_action."""
        # Rate limit → BACKOFF action → retryable (backoff IS a retry strategy)
        assert ErrorClassifier.is_retryable(Exception("rate limit")) is True
        assert ErrorClassifier.is_retryable(Exception("401 Unauthorized")) is False
        assert ErrorClassifier.is_retryable(Exception("content policy")) is False
        assert ErrorClassifier.is_retryable(Exception("500 error")) is True


# ── Structural ───────────────────────────────────────────────────────────────

class TestStructural:
    """Verify taxonomy integrity."""

    def test_11_categories(self):
        """Must have exactly 11 ErrorCategory values."""
        assert len(ErrorCategory) == 11

    def test_5_recovery_actions(self):
        """Must have exactly 5 RecoveryAction values."""
        assert len(RecoveryAction) == 6

    def test_patterns_are_nonempty(self):
        """Every pattern must be a non-empty string."""
        for pattern, _category in _PATTERNS:
            assert isinstance(pattern, str) and len(pattern) > 0
