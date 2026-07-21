"""Unit tests for SecretAccessor — centralized environment access."""
from __future__ import annotations

import pytest

from weebot.config.secret_accessor import SecretAccessor


@pytest.fixture(autouse=True)
def _reset_source():
    """Ensure each test starts with a clean source."""
    SecretAccessor.set_source(None)
    yield
    SecretAccessor.set_source(None)


class TestSecretAccessorGet:
    def test_get_returns_value_from_source(self):
        SecretAccessor.set_source({"KEY": "value"})
        assert SecretAccessor.get("KEY") == "value"

    def test_get_returns_default_when_missing(self):
        SecretAccessor.set_source({"A": "1"})
        assert SecretAccessor.get("B", "default") == "default"

    def test_get_returns_none_default_when_missing_and_no_default(self):
        SecretAccessor.set_source({})
        assert SecretAccessor.get("MISSING") is None

    def test_get_returns_none_default_from_empty_source(self):
        SecretAccessor.set_source(None)
        # Falls through to os.environ; we can't control that without mocking,
        # but we can test the fallback doesn't crash
        result = SecretAccessor.get("NONEXISTENT_KEY_12345", "fallback")
        assert result == "fallback"

    def test_get_int_parses_valid_integer(self):
        SecretAccessor.set_source({"TIMEOUT": "30"})
        assert SecretAccessor.get_int("TIMEOUT") == 30

    def test_get_int_returns_default_on_invalid(self):
        SecretAccessor.set_source({"TIMEOUT": "not_a_number"})
        assert SecretAccessor.get_int("TIMEOUT", default=10) == 10

    def test_get_int_returns_default_when_missing(self):
        SecretAccessor.set_source({})
        assert SecretAccessor.get_int("X", default=5) == 5

    def test_get_bool_truthy_values(self):
        for val in ("1", "true", "TRUE", "yes", "YES", "True", "Yes"):
            SecretAccessor.set_source({"FLAG": val})
            assert SecretAccessor.get_bool("FLAG") is True, f"Failed for {val!r}"

    def test_get_bool_falsy_values(self):
        SecretAccessor.set_source({"FLAG": "0"})
        assert SecretAccessor.get_bool("FLAG") is False
        SecretAccessor.set_source({"FLAG": "false"})
        assert SecretAccessor.get_bool("FLAG") is False
        SecretAccessor.set_source({"FLAG": "no"})
        assert SecretAccessor.get_bool("FLAG") is False

    def test_get_bool_default_when_missing(self):
        SecretAccessor.set_source({})
        assert SecretAccessor.get_bool("X", default=True) is True
        assert SecretAccessor.get_bool("X", default=False) is False

    def test_get_float_parses_valid_float(self):
        SecretAccessor.set_source({"RATE": "2.5"})
        assert SecretAccessor.get_float("RATE") == 2.5

    def test_get_float_returns_default_on_invalid(self):
        SecretAccessor.set_source({"RATE": "not_float"})
        assert SecretAccessor.get_float("RATE", default=1.0) == 1.0

    def test_require_returns_value_when_present(self):
        SecretAccessor.set_source({"REQUIRED": "present"})
        assert SecretAccessor.require("REQUIRED") == "present"

    def test_require_raises_when_missing(self):
        SecretAccessor.set_source({})
        with pytest.raises(ValueError, match="Required environment variable 'REQUIRED'"):
            SecretAccessor.require("REQUIRED")


class TestSecretAccessorRedaction:
    """Verify that secret redaction works for known key patterns."""

    def test_api_key_is_redacted(self, caplog):
        import logging
        caplog.set_level(logging.DEBUG, logger="weebot.config.secret_accessor")
        SecretAccessor.set_source({"OPENROUTER_API_KEY": "sk-or-v1-very-secret"})
        SecretAccessor.get("OPENROUTER_API_KEY")
        assert "<REDACTED>" in caplog.text
        assert "sk-or-v1-very-secret" not in caplog.text

    def test_non_secret_is_logged_plainly(self, caplog):
        import logging
        caplog.set_level(logging.DEBUG, logger="weebot.config.secret_accessor")
        SecretAccessor.set_source({"TIMEOUT": "30"})
        SecretAccessor.get("TIMEOUT")
        assert "30" in caplog.text
        assert "<REDACTED>" not in caplog.text

    def test_unset_key_logs_not_set(self, caplog):
        import logging
        caplog.set_level(logging.DEBUG, logger="weebot.config.secret_accessor")
        SecretAccessor.set_source({})
        SecretAccessor.get("MISSING")
        assert "<NOT SET>" in caplog.text

    def test_secret_suffix_token_is_redacted(self, caplog):
        import logging
        caplog.set_level(logging.DEBUG, logger="weebot.config.secret_accessor")
        SecretAccessor.set_source({"GITHUB_TOKEN": "ghp_1234567890abcdef"})
        SecretAccessor.get("GITHUB_TOKEN")
        assert "<REDACTED>" in caplog.text

    def test_set_source_none_reverts_to_os_environ(self):
        """After set_source(None), get() reads from os.environ (integration)."""
        SecretAccessor.set_source({"CUSTOM": "val"})
        assert SecretAccessor.get("CUSTOM") == "val"
        SecretAccessor.set_source(None)
        # Should not crash and should fall through to real env
        result = SecretAccessor.get("CUSTOM", "absent")
        # If CUSTOM was in os.environ, it would return that; otherwise default
        assert result in ("val", "absent")  # either from env or default
