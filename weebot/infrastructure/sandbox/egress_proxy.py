"""A CONNECT allowlist proxy for the Docker sandbox (H23, step 1).

Standard library only: the same file runs in the sidecar container (``python egress_proxy.py``)
and, in tests, in-process. The sandbox container sits on an internal Docker network whose only
neighbour is this proxy. A call reaches the proxy as ``HTTPS_PROXY=http://<token>:x@egress:3128``;
the token names the hosts that one call was cleared for, and the proxy

* tunnels ``CONNECT host:443`` (or 80) only when the token allows that host;
* resolves the name itself and refuses a private, loopback, link-local or reserved address, so an
  allowed name cannot point back inside the network (an A22-style bypass);
* never reads or alters the tunnel: no TLS interception.

A second listener (the control port) takes ``POST /allow`` and ``POST /revoke`` with the shared
secret, so the host can push the hosts for a call and drop them when it ends.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import ipaddress
import json
import logging
import os
import socket

logger = logging.getLogger(__name__)

PROXY_PORT = 3128
CONTROL_PORT = 3129
ALLOWED_PORTS = frozenset({80, 443})
# Hosts a registry install also needs. Keyed by the host the call was cleared for.
COMPANIONS = {"pypi.org": ("files.pythonhosted.org",)}
_MAX_HEAD = 8192
_IDLE_SECONDS = 300


def _digest(value: str) -> bytes:
    # Compared as hashes, so the time taken does not depend on how much of the secret matched.
    # This file runs alone in the sidecar and cannot import weebot.core.secret_compare.
    return hashlib.sha256(value.encode()).digest()


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


async def _resolve_public(host: str, port: int) -> str | None:
    """The first address of *host*, or None if it has none or any is not public."""
    loop = asyncio.get_running_loop()
    try:
        found = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    addresses = [item[4][0] for item in found]
    if not addresses or not all(_public(a) for a in addresses):
        return None
    return addresses[0]


def _parse_head(head: bytes) -> tuple[str, str, dict[str, str]]:
    lines = head.decode("latin-1").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    headers = {k.lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lines[1:] if ":" in ln)}
    return method, target, headers


class EgressProxy:
    def __init__(
        self,
        control_secret: str,
        *,
        allow_private: bool = False,
        ports: frozenset[int] = ALLOWED_PORTS,
    ) -> None:
        self._secret = control_secret
        self._ports = ports
        self._allow_private = allow_private  # tests only: the fake upstream is on loopback
        self._tokens: dict[str, frozenset[str]] = {}
        self._servers: list[asyncio.Server] = []

    # ── control ────────────────────────────────────────────────────────────────────────

    def allow(self, token: str, hosts: list[str]) -> None:
        names = {h.lower().rstrip(".") for h in hosts if h}
        for name in list(names):
            names.update(COMPANIONS.get(name, ()))
        self._tokens[token] = frozenset(names)

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)

    async def start(
        self, host: str = "0.0.0.0", port: int = PROXY_PORT, control_port: int = CONTROL_PORT
    ) -> tuple[int, int]:
        proxy = await asyncio.start_server(self._on_proxy, host, port)
        control = await asyncio.start_server(self._on_control, host, control_port)
        self._servers = [proxy, control]
        return proxy.sockets[0].getsockname()[1], control.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for server in self._servers:
            server.close()
            await server.wait_closed()

    async def _on_control(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status, body = 400, "bad request"
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            method, path, headers = _parse_head(head)
            presented = headers.get("authorization", "")
            if _digest(presented) != _digest(f"Bearer {self._secret}"):
                status, body = 401, "unauthorized"
            else:
                size = int(headers.get("content-length", "0"))
                payload = json.loads(await reader.readexactly(size))
                if method == "POST" and path == "/allow":
                    self.allow(str(payload["token"]), [str(h) for h in payload["hosts"]])
                    status, body = 200, "ok"
                elif method == "POST" and path == "/revoke":
                    self.revoke(str(payload["token"]))
                    status, body = 200, "ok"
                else:
                    status, body = 404, "not found"
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            TimeoutError,
            ValueError,
            KeyError,
        ):
            status, body = 400, "bad request"
        await _reply(writer, status, body)

    # ── proxy ──────────────────────────────────────────────────────────────────────────

    async def _on_proxy(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
            if len(head) > _MAX_HEAD:
                return await _reply(writer, 431, "header too large")
            method, target, headers = _parse_head(head)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ValueError):
            return await _reply(writer, 400, "bad request")

        token = _token_of(headers.get("proxy-authorization", ""))
        allowed = self._tokens.get(token or "")
        if allowed is None:
            return await _reply(writer, 407, "proxy authentication required")
        if method != "CONNECT":
            return await _reply(writer, 405, "only CONNECT is allowed")
        host, _, port_text = target.rpartition(":")
        host = host.strip("[]").lower().rstrip(".")
        if not port_text.isdigit() or int(port_text) not in self._ports:
            return await _reply(writer, 403, "port not allowed")
        if host not in allowed:
            return await _reply(writer, 403, f"{host} is not cleared for this call")
        port = int(port_text)
        address = host if self._allow_private else await _resolve_public(host, port)
        if address is None:
            return await _reply(writer, 403, f"{host} resolves to a private or unknown address")
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), timeout=15
            )
        except (OSError, TimeoutError):
            return await _reply(writer, 502, "upstream unreachable")
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))


def _token_of(header: str) -> str | None:
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        return base64.b64decode(value).decode().split(":", 1)[0]
    except ValueError:
        return None


async def _reply(writer: asyncio.StreamWriter, status: int, body: str) -> None:
    data = body.encode()
    head = f"HTTP/1.1 {status} {body}\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n"
    writer.write(head.encode() + data)
    with contextlib.suppress(ConnectionError):
        await writer.drain()
    writer.close()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await asyncio.wait_for(reader.read(65536), timeout=_IDLE_SECONDS):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.debug("tunnel closed: %r", exc)
    finally:
        writer.close()


async def _serve(secret: str) -> None:
    await EgressProxy(secret).start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(_serve(os.environ["EGRESS_CONTROL_SECRET"]))
