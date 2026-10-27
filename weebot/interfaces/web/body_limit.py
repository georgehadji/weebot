"""Request body size limit, as pure ASGI so streamed (chunked) bodies are bounded too.

`BaseHTTPMiddleware` cannot stop a body that is being streamed; counting bytes in
`receive` can. One limit covers every route, including the public webhooks that read the
whole body before checking a signature.
"""

from __future__ import annotations

import logging

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

DEFAULT_MAX_BODY_BYTES = 1024 * 1024  # 1 MiB


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._too_large(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised inside the route, so the app's own handler answers 413.
                    raise HTTPException(status_code=413, detail="Request body too large")
            return message

        await self.app(scope, limited_receive, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger.warning("Rejected a %s body over %d bytes", scope.get("path"), self.max_bytes)
        body = b'{"detail":"Request body too large"}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
