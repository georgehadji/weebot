"""Regression test for error classifier auth/billing status codes.

Guards against regression on the 402 Payment Required fix (commit eb9d65c).
"""
from __future__ import annotations

import pytest

from weebot.core.error_classifier import ErrorClassifier, ErrorCategory


class TestErrorClassifierAuth:
    """All 4xx auth/billing codes must classify as AUTH (fail fast, not retry)."""

    def test_401_is_auth(self):
        assert ErrorClassifier.classify(Exception("401 Unauthorized")) == ErrorCategory.AUTH
        assert ErrorClassifier.should_fail_fast(Exception("401 Unauthorized")) is True

    def test_402_is_auth(self):
        assert ErrorClassifier.classify(Exception("402 Payment Required")) == ErrorCategory.AUTH
        assert ErrorClassifier.should_fail_fast(Exception("402 Payment Required")) is True

    def test_403_is_auth(self):
        assert ErrorClassifier.classify(Exception("403 Forbidden")) == ErrorCategory.AUTH
        assert ErrorClassifier.should_fail_fast(Exception("403 Forbidden")) is True

    def test_payment_required_keyword_is_auth(self):
        """Some providers surface 402 in the message body, not the status line."""
        assert ErrorClassifier.classify(
            Exception("Error: payment required — credits exhausted")
        ) == ErrorCategory.AUTH

    def test_api_key_invalid_is_auth(self):
        assert ErrorClassifier.classify(Exception("invalid api key")) == ErrorCategory.AUTH
        assert ErrorClassifier.should_fail_fast(Exception("invalid api key")) is True

    def test_500_is_not_auth(self):
        """Server errors must NOT be classified as AUTH — they are retryable (SERVER_ERROR)."""
        assert ErrorClassifier.classify(Exception("500 Internal Server Error")) == ErrorCategory.SERVER_ERROR
        assert ErrorClassifier.should_fail_fast(Exception("500 Internal Server Error")) is False

    def test_503_is_model_unavailable(self):
        """Service unavailable is MODEL_UNAVAILABLE, not AUTH."""
        assert ErrorClassifier.classify(Exception("503 Service Unavailable")) == ErrorCategory.MODEL_UNAVAILABLE
        assert ErrorClassifier.should_fail_fast(Exception("503 Service Unavailable")) is False

    def test_rate_limit_is_backoff(self):
        """Rate limits produce BACKOFF action (retryable with backoff)."""
        assert ErrorClassifier.classify(Exception("429 Too Many Requests")) == ErrorCategory.RATE_LIMIT
        assert ErrorClassifier.should_fail_fast(Exception("429 Too Many Requests")) is False
        assert ErrorClassifier.is_retryable(Exception("429 Too Many Requests")) is True


class TestErrorClassifierPathErrors:
    """Path errors must be recognized as exploratory, not systemic."""

    def test_cannot_find_path_is_exploratory(self):
        assert ErrorClassifier.is_path_error("Get-ChildItem : Cannot find path 'X' because it does not exist") is True

    def test_access_denied_is_exploratory(self):
        assert ErrorClassifier.is_path_error("Access to the path 'C:\\cache' is denied") is True

    def test_no_such_file_is_exploratory(self):
        assert ErrorClassifier.is_path_error("No such file or directory: /tmp/missing") is True

    def test_normal_error_is_not_exploratory(self):
        assert ErrorClassifier.is_path_error("TypeError: 'NoneType' object has no attribute 'x'") is False
