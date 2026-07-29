"""Proof-of-defect for D1: WebSocket bypasses FailClosedMiddleware.

When no WEEBOT_API_KEY is configured, HTTP requests from non-loopback are
blocked by FailClosedMiddleware (503), but WebSocket connections are accepted
because _websocket_auth returns True for missing API key.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestWebSocketFailOpen:
    """D1 — WebSocket endpoints bypass fail-closed HTTP middleware."""

    def test_websocket_accepts_any_peer_when_no_api_key(self):
        """_websocket_auth returns True for any peer when no API key is set,
        bypassing the fail-closed design intent."""
        from weebot.interfaces.web.main import _websocket_auth

        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {}

        mock_settings = MagicMock()
        mock_settings.weebot_api_key = None

        result = _websocket_auth(ws, mock_settings)
        assert result is True, (
            "_websocket_auth returns True for any peer when no API key is set, "
            "bypassing the fail-closed design intent"
        )

    def test_websocket_auth_vs_failclosed_mismatch(self):
        """HTTP middleware and WebSocket auth have inconsistent policies."""
        from weebot.interfaces.web.main import _websocket_auth

        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {}

        mock_settings = MagicMock()
        mock_settings.weebot_api_key = None

        # WebSocket: returns True unconditionally when no key
        assert _websocket_auth(ws, mock_settings) is True

        # HTTP middleware would check client host and return 503 for remote.
        # WebSocket auth doesn't check client host at all.
        # This is the defect — inconsistent fail-closed enforcement.

    def test_websocket_loopback_should_be_allowed_when_no_key(self):
        """When no API key is set, loopback WebSocket should be allowed
        (consistent with HTTP middleware)."""
        from weebot.interfaces.web.main import _websocket_auth

        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {}
        ws.client = MagicMock()
        ws.client.host = "127.0.0.1"

        mock_settings = MagicMock()
        mock_settings.weebot_api_key = None

        # Current behavior: returns True for ANY host
        # Expected behavior: should check client host like HTTP middleware
        result = _websocket_auth(ws, mock_settings)
        assert result is True  # This is correct for loopback

    def test_websocket_remote_should_be_rejected_when_no_key(self):
        """When no API key is set, remote WebSocket should be rejected
        (consistent with HTTP middleware)."""
        from weebot.interfaces.web.main import _websocket_auth

        ws = MagicMock()
        ws.headers = {}
        ws.query_params = {}
        ws.client = MagicMock()
        ws.client.host = "10.0.0.5"

        mock_settings = MagicMock()
        mock_settings.weebot_api_key = None

        # Current behavior: returns True even for remote host
        # Expected behavior: should return False for remote host when no key
        result = _websocket_auth(ws, mock_settings)
        assert result is True, (
            "Defect: _websocket_auth accepts remote WebSocket connection "
            "when no API key is configured"
        )
