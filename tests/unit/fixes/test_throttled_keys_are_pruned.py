"""The set of throttled clients is trimmed with the buckets.

Found by review of the audit-once fix: ``_throttled`` gained a key for each throttled
client and lost it only when that client was allowed again, so clients that were
throttled once and never came back stayed in it for the life of the process.
"""

from __future__ import annotations

from weebot.interfaces.web import rate_limit


def test_pruning_the_buckets_drops_their_throttled_keys():
    rate_limit._buckets.clear()
    rate_limit._throttled.clear()
    try:
        for i in range(10_001):
            key = f"standard:ip-{i}"
            rate_limit._buckets[key] = rate_limit._TokenBucket(1, 60)
            rate_limit._throttled.add(key)
        rate_limit._prune_buckets()
        assert rate_limit._throttled <= rate_limit._buckets.keys()
    finally:
        rate_limit._buckets.clear()
        rate_limit._throttled.clear()
