"""R18 (audit 2026-10-29): the rate-limit tier depends on the method, not just the path.

The longest path prefix decided alone, so ``/api/sessions/`` ("mutating", 20 a minute)
charged every GET of a session, its events and search to the change budget, and normal UI
polling got 429s. ``POST /api/sessions`` (create) and ``POST /api/chat`` fell to "read".
"""

from __future__ import annotations

import pytest

from weebot.interfaces.web.rate_limit import _get_tier


@pytest.mark.parametrize(
    ("method", "path", "tier"),
    [
        ("GET", "/api/sessions/abc", "read"),
        ("GET", "/api/sessions/abc/events", "read"),
        ("GET", "/api/sessions/search", "read"),
        ("HEAD", "/api/sessions/abc", "read"),
        ("GET", "/api/chat/history", "read"),
        ("GET", "/api/flow/status", "read"),
        ("POST", "/api/sessions", "mutating"),  # create
        ("POST", "/api/sessions/abc/run", "mutating"),
        ("DELETE", "/api/sessions/abc", "mutating"),
        ("POST", "/api/chat", "mutating"),
        ("POST", "/api/chat/stream", "mutating"),
        ("POST", "/api/flow/run", "expensive"),
        ("POST", "/api/webhook/run", "webhook"),
        ("GET", "/api/health", "unlimited"),
        # Only the exact probe paths AuthMiddleware leaves public are unlimited. The rest of
        # /api/health/* needs a key, so a wrong key there must reach the failure budget.
        ("GET", "/api/health/live", "unlimited"),
        ("GET", "/api/health/prometheus", "unlimited"),
        ("GET", "/api/health/status", "read"),
        ("GET", "/api/health/ready", "read"),
        ("GET", "/api/health/metrics", "read"),
        ("GET", "/api/health/", "read"),
        ("GET", "/api/healthz", "read"),
    ],
)
def test_tier_by_method_and_path(method, path, tier):
    assert _get_tier(path, method) == tier


def test_mounted_gateway_routers_are_webhook_tier():
    """The tier table keyed /api/discord/ etc., but the routers mount at /api/gateway/<x>/."""
    from weebot.interfaces.web.routers.discord_webhook import router as discord
    from weebot.interfaces.web.routers.slack_webhook import router as slack
    from weebot.interfaces.web.routers.whatsapp_webhook import router as whatsapp

    for router in (discord, slack, whatsapp):
        assert _get_tier(f"{router.prefix}/x", "POST") == "webhook", router.prefix
    assert _get_tier("/api/gateway/telegram/x", "POST") == "webhook"
