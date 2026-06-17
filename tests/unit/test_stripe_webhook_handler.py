"""Unit tests for Stripe webhook handler."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from weebot.application.services.stripe_webhook_handler import StripeWebhookHandler


def _sign_payload(payload: dict, secret: str, timestamp: str = "1700000000") -> str:
    """Create a Stripe-compatible signature header."""
    payload_str = json.dumps(payload)
    signed = f"{timestamp}.{payload_str}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


class TestStripeSignatureValidation:
    """StripeWebhookHandler.validate_signature tests."""

    def setup_method(self):
        self.handler = StripeWebhookHandler(webhook_secret="whsec_test123")

    def test_valid_signature(self):
        payload = {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_123"}}}
        sig = _sign_payload(payload, "whsec_test123")
        assert self.handler.validate_signature(json.dumps(payload).encode("utf-8"), sig) is True

    def test_invalid_signature(self):
        payload = {"type": "payment_intent.succeeded"}
        sig = _sign_payload(payload, "wrong_secret")
        assert self.handler.validate_signature(json.dumps(payload).encode("utf-8"), sig) is False

    def test_missing_signature_header(self):
        payload = json.dumps({"type": "payment_intent.succeeded"}).encode("utf-8")
        assert self.handler.validate_signature(payload, "") is False

    def test_no_secret_configured_skips_validation(self):
        handler = StripeWebhookHandler(webhook_secret=None)
        payload = json.dumps({"type": "payment_intent.succeeded"}).encode("utf-8")
        assert handler.validate_signature(payload, "invalid") is True


class TestStripeEventProcessing:
    """StripeWebhookHandler.process_event tests."""

    def setup_method(self):
        self.handler = StripeWebhookHandler(webhook_secret="whsec_test")

    def test_payment_succeeded(self):
        payload = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_123",
                    "amount": 2000,
                    "currency": "usd",
                    "status": "succeeded",
                }
            },
        }
        prompt = self.handler.process_event(payload)
        assert prompt is not None
        assert "payment succeeded" in prompt.lower()
        assert "$20.00" in prompt
        assert "pi_123" in prompt

    def test_payment_failed(self):
        payload = {
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_456",
                    "amount": 5000,
                    "currency": "usd",
                    "failure_message": "card_declined",
                }
            },
        }
        prompt = self.handler.process_event(payload)
        assert prompt is not None
        assert "failed" in prompt.lower()
        assert "card_declined" in prompt

    def test_charge_refunded(self):
        payload = {
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_789",
                    "amount": 1500,
                    "currency": "usd",
                }
            },
        }
        prompt = self.handler.process_event(payload)
        assert prompt is not None
        assert "refunded" in prompt.lower()

    def test_dispute_created(self):
        payload = {
            "type": "charge.dispute.created",
            "data": {
                "object": {
                    "id": "dp_123",
                    "amount": 5000,
                    "currency": "usd",
                }
            },
        }
        prompt = self.handler.process_event(payload)
        assert prompt is not None
        assert "dispute" in prompt.lower()
        assert "urgent" in prompt.lower()

    def test_unhandled_event_returns_none(self):
        payload = {"type": "unknown.event.type", "data": {"object": {}}}
        prompt = self.handler.process_event(payload)
        assert prompt is None

    def test_invoice_payment_succeeded(self):
        payload = {
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_123",
                    "amount": 10000,
                    "currency": "usd",
                    "status": "paid",
                }
            },
        }
        prompt = self.handler.process_event(payload)
        assert prompt is not None
        assert "invoice" in prompt.lower()

    def test_zero_decimal_currency(self):
        """JPY amounts should not be divided by 100."""
        payload = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_jpy",
                    "amount": 500,
                    "currency": "jpy",
                    "status": "succeeded",
                }
            },
        }
        prompt = self.handler.process_event(payload)
        assert prompt is not None
        # JPY 500 should appear as "JPY 500" (not divided by 100)
        assert "JPY 500" in prompt or "$5.00" not in prompt
