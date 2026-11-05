"""Which MCP servers are untrusted (H12).

An untrusted server's tools are never read by their name: every one asks, and counts as a
write once untrusted content is in the session (D5). A server nobody registered keeps the
name heuristic in ``tool_guards``. The client manager registers each configured server when
it connects, so in a running process every server is registered, with ``untrusted`` unless
its config says ``trusted``.

Process-wide state, like the settings the guards already read: ``is_outbound_tool`` is a pure
function of a tool name and has no manager to ask.
"""

from __future__ import annotations

from typing import Literal

from weebot.core.mcp_naming import build_namespaced_name, parse_namespaced_name

_UNTRUSTED: set[str] = set()


def _key(server_name: str) -> str:
    # Through the builder, so the key is spelled the way the tool names carry it.
    parsed = parse_namespaced_name(build_namespaced_name(server_name, "x"))
    return (parsed[0] if parsed else server_name).lower()


def register_server(server_name: str, trust: Literal["trusted", "untrusted"]) -> None:
    key = _key(server_name)
    if trust == "untrusted":
        _UNTRUSTED.add(key)
    else:
        _UNTRUSTED.discard(key)


def unregister_server(server_name: str) -> None:
    _UNTRUSTED.discard(_key(server_name))


def is_untrusted_tool(namespaced_tool: str) -> bool:
    """True when *namespaced_tool* (``mcp__<server>__<tool>``) is on an untrusted server."""
    parsed = parse_namespaced_name(namespaced_tool)
    return parsed is not None and parsed[0].lower() in _UNTRUSTED
