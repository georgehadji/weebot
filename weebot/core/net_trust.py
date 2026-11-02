"""Pure checks behind the web API's loopback trust: peer, Host and Origin.

With no API key, a request from the machine's own loopback address counts as the operator.
A hostile web page reaches that address through the operator's browser, carrying a Host or an
Origin that is not the operator's: DNS rebinding makes its own domain resolve to 127.0.0.1, and
a cross-site WebSocket handshake is not covered by CORS. These functions say which Host and
Origin values are the operator's. They do no I/O and read no settings; the ASGI shell in
``weebot/interfaces/web/host_guard.py`` supplies the values and acts on the answer.
"""

from __future__ import annotations

# The exact peer addresses that count as "this machine". One home: the web auth module and
# the host guard both use this set, so identity trust and the Host check cannot disagree.
LOOPBACK_PEERS: frozenset[str] = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

# Host names a browser uses to reach the local API. An IPv6 literal appears without brackets.
DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

_BAD_HOST_CHARS = frozenset("@/?# \t\r\n\\")


def is_loopback_peer(peer: str | None) -> bool:
    return bool(peer) and peer in LOOPBACK_PEERS


def _split_host(value: str | None) -> str | None:
    """The lower-cased host of a Host header or a configured name, port removed.

    None when the text is not a well-formed host: empty, an unbracketed IPv6 literal, a
    non-numeric port, or any character that could smuggle a different host (``@``, ``/``).
    """
    if not value:
        return None
    text = value.strip()
    if not text or any(ch in _BAD_HOST_CHARS for ch in text):
        return None
    if text.startswith("["):
        end = text.find("]")
        if end == -1:
            return None
        host, rest = text[1:end], text[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
    elif text.count(":") > 1:
        return None
    elif ":" in text:
        host, _, port = text.partition(":")
        if not port.isdigit():
            return None
    else:
        host = text
    return host.lower() or None


def parse_allowed_hosts(text: str | None) -> frozenset[str]:
    """Host names from a comma-separated setting. Blanks, bad entries and ports are dropped."""
    if not text:
        return frozenset()
    hosts = (_split_host(part) for part in text.split(","))
    return frozenset(h for h in hosts if h)


def host_allowed(host_header: str | None, allowed: frozenset[str]) -> bool:
    """True when the Host header names one of *allowed* (any port)."""
    host = _split_host(host_header)
    return host is not None and host in allowed


def _origin_key(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def origin_allowed(origin: str | None, allowed_origins: list[str] | frozenset[str]) -> bool:
    """True when *origin* is exactly one of *allowed_origins*. ``null`` and empty are not."""
    if not origin:
        return False
    key = _origin_key(origin)
    return key != "null" and key in {_origin_key(o) for o in allowed_origins}
