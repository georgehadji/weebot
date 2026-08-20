"""Unit tests for M8 WhatsApp webhook signature verification (fail-closed)."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

from weebot.interfaces.gateways.whatsapp import WhatsAppAdapter


class TestWhatsAppSignatureVerification:
    """Tests for WhatsAppAdapter.verify_signature fail-closed behaviour."""

    def _make_adapter(
        self, app_secret: str | None = None, unsigned_allowed: bool = False
    ) -> WhatsAppAdapter:
        """Build a WhatsAppAdapter with mocked dependencies."""
        adapter = WhatsAppAdapter(
            token="token",
            phone_number_id="12345",
            state_repo=MagicMock(),
            llm=MagicMock(),
            app_secret=app_secret,
        )
        return adapter

    def test_no_secret_flag_off_returns_false(self) -> None:
        adapter = self._make_adapter(app_secret=None)
        mock_settings = MagicMock()
        mock_settings.whatsapp_allow_unsigned_webhooks = False

        with patch("weebot.config.settings.WeebotSettings", return_value=mock_settings):
            result = adapter.verify_signature(b"body", "sig")

        assert result is False

    def test_no_secret_flag_on_returns_true(self) -> None:
        adapter = self._make_adapter(app_secret=None)
        mock_settings = MagicMock()
        mock_settings.whatsapp_allow_unsigned_webhooks = True

        with patch("weebot.config.settings.WeebotSettings", return_value=mock_settings):
            result = adapter.verify_signature(b"body", "sig")

        assert result is True

    def test_valid_hmac_accepted(self) -> None:
        adapter = self._make_adapter(app_secret="secret")
        body = b"test-body"
        expected_sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()

        result = adapter.verify_signature(body, expected_sig)
        assert result is True

    def test_tampered_body_rejected(self) -> None:
        adapter = self._make_adapter(app_secret="secret")
        body = b"test-body"
        wrong_sig = "sha256=" + hmac.new(b"secret", b"other-body", hashlib.sha256).hexdigest()

        result = adapter.verify_signature(body, wrong_sig)
        assert result is False

    def test_missing_sha256_prefix_rejected(self) -> None:
        adapter = self._make_adapter(app_secret="secret")
        body = b"test-body"
        raw_hex = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

        result = adapter.verify_signature(body, raw_hex)
        assert result is False
