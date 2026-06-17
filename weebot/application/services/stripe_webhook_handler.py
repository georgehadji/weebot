"""Stripe Webhook Handler — validates and processes Stripe webhook events.

Maps Stripe events to agent-actionable prompts and dispatches alerts
through the gateway delivery system.

Requires STRIPE_WEBHOOK_SECRET in the environment for signature validation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maps Stripe event types to agent prompt templates
EVENT_PROMPT_MAP: dict[str, str] = {
    "payment_intent.succeeded": (
        "A Stripe payment succeeded. Details: {details}. "
        "Thank the customer and update our records."
    ),
    "payment_intent.payment_failed": (
        "A Stripe payment failed. Details: {details}. "
        "Investigate the failure reason and suggest next steps."
    ),
    "charge.refunded": (
        "A Stripe charge was refunded. Details: {details}. "
        "Update our records and notify the customer if needed."
    ),
    "charge.dispute.created": (
        "A Stripe dispute was created. Details: {details}. "
        "This is urgent — investigate immediately and prepare evidence."
    ),
    "charge.dispute.closed": (
        "A Stripe dispute was resolved. Details: {details}. "
        "Update our records."
    ),
    "invoice.payment_succeeded": (
        "A Stripe invoice payment succeeded. Details: {details}. "
        "Mark the invoice as paid."
    ),
    "invoice.payment_failed": (
        "A Stripe invoice payment failed. Details: {details}. "
        "Follow up with the customer about the failed payment."
    ),
    "customer.subscription.updated": (
        "A Stripe subscription was updated. Details: {details}. "
        "Update our records."
    ),
    "customer.subscription.deleted": (
        "A Stripe subscription was canceled. Details: {details}. "
        "Update our records and send a confirmation."
    ),
}


class StripeWebhookHandler:
    """Validates and processes incoming Stripe webhook events."""

    def __init__(self, webhook_secret: str | None = None) -> None:
        self._webhook_secret = webhook_secret

    def validate_signature(
        self,
        payload: bytes,
        sig_header: str,
    ) -> bool:
        """Validate the Stripe webhook signature.

        Args:
            payload: Raw request body.
            sig_header: The ``stripe-signature`` header value.

        Returns:
            True if the signature is valid.
        """
        if not self._webhook_secret:
            logger.warning("No webhook secret configured — skipping signature validation")
            return True

        if not sig_header:
            logger.warning("Missing stripe-signature header")
            return False

        try:
            # Parse the signature header
            # Format: t=<timestamp>,v1=<signature>[,v1=<signature>]
            parts = {}
            for item in sig_header.split(","):
                key, _, value = item.partition("=")
                parts[key.strip()] = value.strip()

            timestamp = parts.get("t", "")
            expected_sig = parts.get("v1", "")

            # Compute the expected signature
            signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
            computed_sig = hmac.new(
                self._webhook_secret.encode("utf-8"),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()

            # Constant-time comparison
            if not hmac.compare_digest(computed_sig, expected_sig):
                logger.warning("Stripe webhook signature mismatch")
                return False

            return True
        except Exception as exc:
            logger.error("Stripe signature validation failed: %s", exc)
            return False

    def process_event(self, payload: dict[str, Any]) -> str | None:
        """Process a Stripe event and return an agent prompt.

        Args:
            payload: The parsed Stripe event object.

        Returns:
            An agent prompt string, or None if the event type is not handled.
        """
        event_type = payload.get("type", "")
        data = payload.get("data", {}).get("object", {})

        prompt_template = EVENT_PROMPT_MAP.get(event_type)
        if prompt_template is None:
            logger.debug("Unhandled Stripe event type: %s", event_type)
            return None

        # Build a readable summary of the event object
        details = self._summarize_object(event_type, data)
        prompt = prompt_template.format(details=details)
        logger.info("Stripe event %s → agent prompt generated", event_type)
        return prompt

    @staticmethod
    def _summarize_object(event_type: str, obj: dict[str, Any]) -> str:
        """Build a human-readable summary of a Stripe resource object."""
        parts: list[str] = []

        obj_id = obj.get("id", "unknown")
        parts.append(f"ID: {obj_id}")

        amount = obj.get("amount")
        if amount:
            # Stripe amounts are in the currency's smallest unit.
            # Zero-decimal currencies (JPY, KRW, VND, etc.) don't divide by 100.
            currency = obj.get("currency", "usd").upper()
            zero_decimal = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW",
                           "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF",
                           "XOF", "XPF"}
            if currency in zero_decimal:
                parts.append(f"Amount: {currency} {amount}")
            else:
                dollars = amount / 100.0
                parts.append(f"Amount: ${dollars:.2f} {currency}")

        status = obj.get("status")
        if status:
            parts.append(f"Status: {status}")

        customer = obj.get("customer") or obj.get("customer_email")
        if customer:
            parts.append(f"Customer: {customer}")

        desc = obj.get("description")
        if desc:
            parts.append(f"Description: {desc}")

        failure_msg = obj.get("failure_message") or obj.get("failure_code")
        if failure_msg:
            parts.append(f"Failure: {failure_msg}")

        created = obj.get("created")
        if created:
            parts.append(f"Created: {created}")

        return " | ".join(parts)
