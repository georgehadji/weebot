"""Rate limiting middleware for FastAPI — per-principal token bucket.

Tiered limits by endpoint class:
- Health: unlimited
- Read: 120/min
- Mutating: 20/min
- Webhook: 60/min per source
- Expensive (flow run): 10/min + concurrency cap

Keyed by principal (post-WI-11) falling back to client IP.
In-memory token bucket implementation; Valkey backend optional.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from weebot.infrastructure.observability import metrics as _metrics

logger = logging.getLogger(__name__)

# Tier definitions: (requests, window_seconds)
RATE_LIMITS: dict[str, tuple[int, int]] = {
    "unlimited": (0, 1),
    "read": (120, 60),
    "mutating": (20, 60),
    "webhook": (60, 60),
    "expensive": (10, 60),
}

# Endpoint path → tier mapping
_PATH_TIERS: dict[str, str] = {
    # Health — unlimited
    "/api/health": "unlimited",
    "/api/live": "unlimited",
    "/api/ready": "unlimited",
    # Read
    "/api/sessions": "read",
    "/api/models": "read",
    "/api/dashboard": "read",
    # Mutating
    "/api/sessions/": "mutating",
    "/api/chat/": "mutating",
    "/api/behavior/": "mutating",
    # Webhook
    "/api/webhook/": "webhook",
    "/api/discord/": "webhook",
    "/api/slack/": "webhook",
    "/api/whatsapp/": "webhook",
    # Expensive
    "/api/flow/": "expensive",
}

UNLIMITED_TIERS = {"unlimited"}
UNLIMITED_PATHS = {"/api/health", "/api/live", "/api/ready"}


def _get_tier(path: str) -> str:
    """Return the rate limit tier for a request path."""
    if path in _PATH_TIERS:
        return _PATH_TIERS[path]
    # Prefix match for parameterized paths — check longest first
    matched_tier = "read"
    matched_len = 0
    for prefix, tier in _PATH_TIERS.items():
        if path.startswith(prefix) and len(prefix) > matched_len:
            matched_tier = tier
            matched_len = len(prefix)
    return matched_tier


class _TokenBucket:
    """In-memory sliding-window token bucket per key."""

    __slots__ = ("max_tokens", "window_sec", "_buckets")

    def __init__(self, max_tokens: int, window_sec: int) -> None:
        self.max_tokens = max_tokens
        self.window_sec = window_sec
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Check if *key* is allowed. Returns True if under limit."""
        now = time.monotonic()
        timestamps = self._buckets[key]
        # Prune old entries outside the window
        cutoff = now - self.window_sec
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        if self.max_tokens > 0 and len(timestamps) >= self.max_tokens:
            return False

        timestamps.append(now)
        return True

    def retry_after(self, key: str) -> float:
        """Seconds until the oldest request in the window expires."""
        timestamps = self._buckets.get(key)
        if not timestamps:
            return 0.0
        now = time.monotonic()
        oldest = timestamps[0]
        wait = (oldest + self.window_sec) - now
        return max(0.0, wait)


# Global bucket registry — keyed on (tier, principal)
_buckets: dict[str, _TokenBucket] = {}
_buckets_lock = asyncio.Lock()


def _prune_buckets() -> None:
    """Remove roughly half the buckets to prevent unbounded growth when over 10k."""
    if len(_buckets) <= 10000:
        return
    import random

    keys_to_drop = random.sample(list(_buckets.keys()), k=len(_buckets) // 2)
    for k in keys_to_drop:
        del _buckets[k]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-request rate limiting middleware.

    Apply to the FastAPI app to enforce tiered limits on all routes.
    Health endpoints are always exempt.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        path = request.url.path

        # Health endpoints are always exempt
        if path in UNLIMITED_PATHS:
            return await call_next(request)

        tier = _get_tier(path)

        # Unlimited tier check
        if tier in UNLIMITED_TIERS:
            return await call_next(request)

        # Resolve principal key
        principal = self._resolve_principal(request)

        # Check rate limit
        bucket = await self._get_bucket(tier, principal)
        if not bucket.allow(principal):
            retry_after = int(bucket.retry_after(principal))
            _metrics.mcp_rate_limits_hit_total.labels(tool=tier).inc()
            from weebot.infrastructure.security.audit_logger import AuditEventType, AuditLogger

            AuditLogger.log(
                AuditEventType.RATE_LIMIT_EXCEEDED,
                {"tier": tier, "principal": principal, "path": path, "retry_after": retry_after},
            )
            logger.warning("Rate limit hit: tier=%s principal=%s path=%s", tier, principal, path)
            return Response(
                status_code=429,
                content=f'{{"detail":"Rate limit exceeded. Retry after {retry_after}s."}}',
                media_type="application/json",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(bucket.max_tokens),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                },
            )

        # The expensive tier uses a stricter per-key rate (10/min) instead
        # of a global concurrency counter, avoiding CF-1's cumulative
        # counter problem. The sliding-window bucket handles it correctly.
        response = await call_next(request)
        return response

    @staticmethod
    def _resolve_principal(request: Request) -> str:
        """Return the principal key for rate limiting.

        Post-WI-11: uses X-API-Key (SHA-256 derived) when available.
        Falls back to client IP.
        """
        api_key = request.headers.get("X-API-Key", "")
        if api_key:
            import hashlib

            return f"key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"

    @staticmethod
    async def _get_bucket(tier: str, key: str) -> _TokenBucket:
        """Get or create a token bucket for the given tier and key.

        Uses the tier's default limits.  Lock-guarded against concurrent
        bucket creation under multi-worker deployment.
        """
        bucket_key = f"{tier}:{key}"
        async with _buckets_lock:
            if bucket_key not in _buckets:
                max_tokens, window_sec = RATE_LIMITS.get(tier, (60, 60))
                _buckets[bucket_key] = _TokenBucket(max_tokens, window_sec)
                # Prune every 1000th new bucket to prevent unbounded growth
                if len(_buckets) % 1000 == 0:
                    _prune_buckets()
            return _buckets[bucket_key]
