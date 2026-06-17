"""Unit tests for WhatsApp, Signal, and Email gateway adapters."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from weebot.interfaces.gateways.whatsapp import WhatsAppAdapter
from weebot.interfaces.gateways.signal import SignalAdapter
from weebot.interfaces.gateways.email import EmailAdapter
from weebot.interfaces.gateways.base import GatewayResponse


# Patch SafetyChecker to avoid ChatOpenAI init during tests
@pytest.fixture(autouse=True)
def _mock_safety():
    with patch("weebot.interfaces.gateways.base.SafetyChecker") as mock:
        instance = mock.return_value
        instance.is_critical_operation.return_value = False
        yield


class TestWhatsAppAdapter:
    """WhatsAppAdapter send_response and message parsing."""

    def setup_method(self):
        self.adapter = WhatsAppAdapter(
            token="test-token",
            phone_number_id="123456789",
        )

    @pytest.mark.asyncio
    async def test_send_response_failure_returns_false(self):
        """send_response with success=False should return False."""
        resp = GatewayResponse(text="Hello", platform="whatsapp", external_id="5551234", success=False)
        result = await self.adapter.send_response(resp)
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_webhook_valid(self):
        verified, challenge = self.adapter.verify_webhook("subscribe", "weebot-verify", "challenge123")
        assert verified is True
        assert challenge == "challenge123"

    @pytest.mark.asyncio
    async def test_verify_webhook_invalid_token(self):
        verified, _ = self.adapter.verify_webhook("subscribe", "wrong-token", "challenge123")
        assert verified is False

    @pytest.mark.asyncio
    async def test_verify_webhook_wrong_mode(self):
        verified, _ = self.adapter.verify_webhook("unsubscribe", "weebot-verify", "challenge123")
        assert verified is False

    def test_parse_incoming_text_message(self):
        body = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5551234",
                            "id": "msg_1",
                            "type": "text",
                            "text": {"body": "Hello from WhatsApp"},
                        }],
                    },
                }],
            }],
        }
        messages = self.adapter.parse_incoming(body)
        assert len(messages) == 1
        assert messages[0].external_id == "5551234"
        assert messages[0].text == "Hello from WhatsApp"
        assert messages[0].platform == "whatsapp"

    def test_parse_incoming_empty_body(self):
        messages = self.adapter.parse_incoming({})
        assert len(messages) == 0

    def test_parse_incoming_no_messages(self):
        body = {"entry": [{"changes": [{"value": {"metadata": {}}}]}]}
        messages = self.adapter.parse_incoming(body)
        assert len(messages) == 0


class TestSignalAdapter:
    """SignalAdapter send_response and mock receiving."""

    def setup_method(self):
        self.adapter = SignalAdapter(
            rest_url="http://localhost:8080",
            account_number="+1234567890",
        )

    @pytest.mark.asyncio
    async def test_send_response_failure_returns_false(self):
        resp = GatewayResponse(text="Hi", platform="signal", external_id="+5551234", success=False)
        result = await self.adapter.send_response(resp)
        assert result is False

    def test_adapter_start_stop(self):
        """Start and stop should not raise."""
        import asyncio
        asyncio.get_event_loop().run_until_complete(self.adapter.start())
        asyncio.get_event_loop().run_until_complete(self.adapter.stop())


class TestEmailAdapter:
    """EmailAdapter initialization and send_response."""

    def setup_method(self):
        self.adapter = EmailAdapter(
            imap_server="imap.test.com",
            imap_user="test@test.com",
            imap_password="test-pass",
            smtp_server="smtp.test.com",
            smtp_port=587,
        )

    @pytest.mark.asyncio
    async def test_send_response_failure_returns_false(self):
        resp = GatewayResponse(text="Hi", platform="email", external_id="user@test.com", success=False)
        result = await self.adapter.send_response(resp)
        assert result is False

    def test_get_text_body_plain(self):
        """Extract plain text body from a simple email."""
        import email
        msg = email.message_from_string("Subject: Test\n\nHello World")
        body = self.adapter._get_text_body(msg)
        assert body == "Hello World"

    def test_get_text_body_multipart(self):
        """Extract text from multipart email."""
        import email
        raw = (
            "Content-Type: multipart/alternative; boundary=boundary\n\n"
            "--boundary\n"
            "Content-Type: text/plain\n\n"
            "Plain text body\n"
            "--boundary\n"
            "Content-Type: text/html\n\n"
            "<html><body>HTML body</body></html>\n"
            "--boundary--"
        )
        msg = email.message_from_string(raw)
        body = self.adapter._get_text_body(msg)
        assert body == "Plain text body"

    def test_get_text_body_empty(self):
        """Empty message returns empty string."""
        import email
        msg = email.message_from_string("Subject: Empty\n\n")
        body = self.adapter._get_text_body(msg)
        assert body == ""
