"""Refuse a foreign Host from a loopback peer, and a foreign Origin on a WebSocket handshake.

With no API key, a loopback peer counts as the operator (``auth.py``). A hostile page reaches
that peer through the operator's browser in two ways this guard closes:

* DNS rebinding: the page's own domain re-resolves to 127.0.0.1, so the browser sends the
  request with ``Host: evil.test``. A remote peer has no loopback trust to abuse, so only a
  loopback peer is held to the Host rule.
* A cross-site WebSocket: CORS does not apply to a handshake, so the browser connects and
  sends ``Origin: http://evil.test``. A missing ``Origin`` is allowed (non-browser clients send
  none).

It is pure ASGI so one place covers HTTP and WebSocket scopes, and a new route cannot forget
it. The decisions are the pure functions in ``weebot.core.net_trust``.
"""

from __future__ import annotations

import logging

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from weebot.core.net_trust import (
    DEFAULT_ALLOWED_HOSTS,
    host_allowed,
    is_loopback_peer,
    origin_allowed,
    parse_allowed_hosts,
)

logger = logging.getLogger(__name__)

# 4003 is already the routes' own "not authorised" close; keep the guard distinguishable.
FORBIDDEN_CLOSE_CODE = 4403


def _allowed_hosts() -> frozenset[str]:
    from weebot.config.secret_accessor import SecretAccessor

    return DEFAULT_ALLOWED_HOSTS | parse_allowed_hosts(SecretAccessor.get("WEEBOT_ALLOWED_HOSTS"))


class HostGuardMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self._origins = list(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        client = scope.get("client")
        peer = client[0] if client else None

        reason = None
        if is_loopback_peer(peer) and not host_allowed(headers.get("host"), _allowed_hosts()):
            reason = "Invalid Host header"
        elif scope["type"] == "websocket":
            origin = headers.get("origin")
            if origin is not None and not origin_allowed(origin, self._origins):
                reason = "Origin not allowed"

        if reason is None:
            await self.app(scope, receive, send)
            return

        logger.warning("Refused %s from %s: %s", scope["type"], peer, reason)
        if scope["type"] == "websocket":
            await WebSocketClose(code=FORBIDDEN_CLOSE_CODE, reason=reason)(scope, receive, send)
        else:
            await PlainTextResponse(reason, status_code=421)(scope, receive, send)
