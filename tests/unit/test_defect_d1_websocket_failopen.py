"""Regression tests for D1: WebSocket must not bypass FailClosedMiddleware.

History
-------
This file began as a proof-of-defect: when no ``WEEBOT_API_KEY`` was
configured, ``_websocket_auth`` returned ``True`` unconditionally, so remote
WebSocket clients were accepted while the equivalent HTTP request was refused
with 503 by ``FailClosedMiddleware``.

The defect is fixed — ``_websocket_auth`` now applies the same loopback-only
policy as the HTTP path.  The assertions below have been inverted accordingly:
they now pin the *correct* behaviour so the fail-open cannot silently return.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from weebot.interfaces.web.main import _LOOPBACK, _websocket_auth


def _make_ws(host: str | None):
    """Build a mock WebSocket whose peer address is *host*."""
    ws = MagicMock()
    ws.headers = {}
    ws.query_params = {}
    if host is None:
        ws.client = None
    else:
        ws.client = MagicMock()
        ws.client.host = host
    return ws


def _no_key_settings():
    settings = MagicMock()
    settings.weebot_api_key = None
    return settings


class TestWebSocketFailClosed:
    """D1 — WebSocket auth must match the HTTP fail-closed policy."""

    def test_remote_peer_is_rejected_when_no_api_key(self):
        """A non-loopback peer must be refused when no API key is configured."""
        assert _websocket_auth(_make_ws("10.0.0.5"), _no_key_settings()) is False

    def test_loopback_peer_is_allowed_when_no_api_key(self):
        """Loopback keeps working without a key — the single-user desktop case."""
        for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            assert host in _LOOPBACK, f"{host} should be a recognised loopback address"
            assert _websocket_auth(_make_ws(host), _no_key_settings()) is True, host

    def test_unknown_peer_is_rejected_when_no_api_key(self):
        """A connection with no resolvable client address is refused, not allowed."""
        assert _websocket_auth(_make_ws(None), _no_key_settings()) is False

    def test_policy_matches_http_failclosed_middleware(self):
        """WebSocket and HTTP must agree: loopback allowed, remote refused.

        The original defect was precisely this inconsistency — HTTP returned
        503 for remote callers while WebSocket accepted them.
        """
        settings = _no_key_settings()
        remote_allowed = _websocket_auth(_make_ws("203.0.113.9"), settings)
        loopback_allowed = _websocket_auth(_make_ws("127.0.0.1"), settings)

        assert loopback_allowed is True
        assert remote_allowed is False
        assert remote_allowed != loopback_allowed, (
            "WebSocket auth must distinguish loopback from remote when no API "
            "key is set, matching FailClosedMiddleware's HTTP behaviour"
        )
