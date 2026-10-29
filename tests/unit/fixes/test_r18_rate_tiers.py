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
    ],
)
def test_tier_by_method_and_path(method, path, tier):
    assert _get_tier(path, method) == tier
