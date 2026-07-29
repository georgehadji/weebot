"""Tests for the CredentialSanitizer — masks passwords, tokens, API keys."""
from __future__ import annotations

import pytest
from weebot.core.credential_sanitizer import sanitize, has_credentials


class TestCredentialSanitizer:
    """Tests for credential redaction."""

    # ── password patterns ──

    @pytest.mark.parametrize(
        "raw,expected_contains",
        [
            ("password=secret123", "password=***REDACTED***"),
            ("password: mypass", "password: ***REDACTED***"),
            ("passwd=abc", "passwd=***REDACTED***"),
            ("pwd=letmein", "pwd=***REDACTED***"),
            ("secret=mysecret", "secret=***REDACTED***"),
            # colon-separated: "email: x password: y"
            ("email: user@example.com password: T3ss3ra!!",
             "password: ***REDACTED***"),
        ],
    )
    def test_password_patterns(self, raw: str, expected_contains: str) -> None:
        result = sanitize(raw)
        assert expected_contains in result
        assert "T3ss3ra" not in result if "T3ss3ra" in raw else True
        assert "secret123" not in result if "secret123" in raw else True

    # ── API key patterns ──

    @pytest.mark.parametrize(
        "raw",
        [
            "api_key=sk-abc123def456",
            "apikey: abcdefghijklmnop",
            "token=ghp_1234567890abcdef",
        ],
    )
    def test_api_key_patterns(self, raw: str) -> None:
        result = sanitize(raw)
        assert "***REDACTED***" in result

    # ── OpenAI / Anthropic keys ──

    @pytest.mark.parametrize(
        "raw",
        [
            "sk-proj-abc123def456ghijklmnopqrstuvwxyz",
            "sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456",
        ],
    )
    def test_openai_anthropic_keys(self, raw: str) -> None:
        result = sanitize(raw)
        assert "***REDACTED-API-KEY***" in result

    # ── JWT tokens ──

    def test_jwt_token(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = sanitize(jwt)
        assert "***REDACTED-JWT***" in result
        assert jwt not in result

    # ── AWS keys ──

    def test_aws_key(self) -> None:
        result = sanitize("AKIAIOSFODNN7EXAMPLE")
        assert "***REDACTED-AWS-KEY***" in result

    # ── no-op for clean text ──

    def test_clean_text_passes_through(self) -> None:
        text = "The weather in Athens is sunny today"
        assert sanitize(text) == text

    # ── has_credentials ──

    def test_has_credentials_positive(self) -> None:
        assert has_credentials("password=secret")

    def test_has_credentials_negative(self) -> None:
        assert not has_credentials("hello world")
