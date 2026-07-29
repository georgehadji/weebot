"""Unit tests for the rate limiting middleware.

Tests cover token bucket behavior, tier mapping, and health endpoint exemption.
"""
from __future__ import annotations

from collections import deque

from weebot.interfaces.web.rate_limit import _TokenBucket, _get_tier, RATE_LIMITS


class TestTokenBucket:
    """Verify the in-memory sliding-window token bucket."""

    def test_allows_up_to_limit(self):
        b = _TokenBucket(5, 60)
        for _ in range(5):
            assert b.allow("user-1")
        assert not b.allow("user-1")

    def test_allows_different_keys_independently(self):
        b = _TokenBucket(2, 60)
        assert b.allow("alice")
        assert b.allow("alice")
        assert not b.allow("alice")
        assert b.allow("bob")  # bob has his own bucket

    def test_allows_after_window_expires(self):
        b = _TokenBucket(1, 5)
        assert b.allow("u")
        assert not b.allow("u")
        # Simulate window passing by manipulating internal timestamps
        import time as _time
        b._buckets["u"] = deque([_time.monotonic() - 10])  # 10s ago (outside 5s window)
        assert b.allow("u")  # old entry pruned, new one allowed

    def test_retry_after(self):
        b = _TokenBucket(1, 10)
        b.allow("u")
        wait = b.retry_after("u")
        assert 0 < wait <= 10

    def test_retry_after_empty(self):
        b = _TokenBucket(5, 60)
        assert b.retry_after("nonexistent") == 0.0

    def test_unlimited_bucket(self):
        """Unlimited tier (max_tokens=0) should allow everything."""
        b = _TokenBucket(0, 1)
        for _ in range(100):
            assert b.allow("u")


class TestTierMapping:
    """Verify endpoint-to-tier mapping."""

    def test_health_unlimited(self):
        assert _get_tier("/api/health") == "unlimited"
        assert _get_tier("/api/live") == "unlimited"
        assert _get_tier("/api/ready") == "unlimited"

    def test_read_tier(self):
        assert _get_tier("/api/sessions") == "read"
        assert _get_tier("/api/models") == "read"

    def test_mutating_tier(self):
        assert _get_tier("/api/sessions/abc") == "mutating"
        assert _get_tier("/api/chat/send") == "mutating"

    def test_webhook_tier(self):
        assert _get_tier("/api/webhook/run") == "webhook"
        assert _get_tier("/api/discord/events") == "webhook"
        assert _get_tier("/api/slack/commands") == "webhook"

    def test_expensive_tier(self):
        assert _get_tier("/api/flow/run") == "expensive"

    def test_unknown_defaults_to_read(self):
        assert _get_tier("/api/unknown") == "read"

    def test_limits_are_reasonable(self):
        """Sanity check: limits are positive for non-unlimited tiers."""
        for tier, (tokens, window) in RATE_LIMITS.items():
            if tier == "unlimited":
                continue
            assert tokens > 0, f"{tier} should have a positive limit"
            assert window > 0, f"{tier} should have a positive window"
