"""The one place an MCP tool's public name is built and taken apart.

Phase 1.2 of ``tasks/specs/arch_audit_2026_09_remediation_plan.md``.

There were two conventions. ``mcp_tool_registry_bridge`` built and parsed
``mcp__<server>__<tool>``; ``MCPClientManager.get_all_tools`` built
``mcp_<server>_<tool>`` -- single underscores -- and its ``call_tool``
took the same shape apart again. Both halves of each pair agreed with
themselves, so neither had a failing test, and the two never met in a
place that compared them.

Three things broke on the seam:

1. ``core.trust_boundary.is_untrusted_tool`` tests for ``mcp__``. The
   names that actually reached the executor were the single-underscore
   ones, so MCP output was neither wrapped in the prompt-injection fence
   nor marked as tainting egress -- the control CLAUDE.md requires for
   untrusted inbound content, absent on the one source that is untrusted
   by definition.
2. ``UNTRUSTED_OUTPUT_TOOLS`` listed ``"mcp_tool"`` and ``"mcp_call"`` as
   a literal fallback. No tool was ever registered under either name.
   The list covered two names that did not exist.
3. ``MCPToolRegistryBridge._register_all_tools`` fed those names to a
   parser that requires ``mcp__`` and skipped every one that failed. It
   registered nothing, from any server, ever -- and reported the count it
   registered, which was zero, at INFO.

One module now owns the convention, and it is ``core`` rather than either
side, because both the infrastructure client and the application bridge
need it and neither may import the other.

The prefix is deliberately ``mcp__`` and not ``mcp_``. Widening the
untrusted test to a single underscore would silently mark any future tool
whose name begins with those four characters as untrusted passthrough --
the same class of accident in the other direction, and harder to notice
because it fails toward "everything is suspicious".
"""

from __future__ import annotations

MCP_NAMESPACE_PREFIX = "mcp__"
_SEPARATOR = "__"


def _sanitize(part: str) -> str:
    """Remove characters that would make a name ambiguous to parse."""
    return part.replace(".", "_").replace("-", "_")


def build_namespaced_name(server_name: str, tool_name: str) -> str:
    """Return the public name for *tool_name* on *server_name*.

    ``build_namespaced_name("xapi", "search_posts")`` ->
    ``"mcp__xapi__search_posts"``.

    A server already carrying the prefix is not double-prefixed, so a
    config that spells its server ``mcp__stripe`` produces
    ``mcp__stripe__charge`` rather than ``mcp__mcp__stripe__charge``.
    """
    safe_server = _sanitize(server_name)
    safe_tool = _sanitize(tool_name)
    if safe_server.startswith(MCP_NAMESPACE_PREFIX):
        safe_server = safe_server[len(MCP_NAMESPACE_PREFIX) :]
    return f"{MCP_NAMESPACE_PREFIX}{safe_server}{_SEPARATOR}{safe_tool}"


def parse_namespaced_name(namespaced: str) -> tuple[str, str] | None:
    """Reverse :func:`build_namespaced_name`.

    Returns ``(server_name, tool_name)``, or ``None`` when *namespaced*
    does not follow the convention. ``None`` rather than an exception
    because callers legitimately mix MCP and native tool names in one
    list and need to ask the question cheaply.

    Note that the sanitisation in :func:`build_namespaced_name` is not
    reversible: a server literally named ``a-b`` round-trips as ``a_b``.
    That is why the built name, not the raw server name, is what gets
    stored and matched on.
    """
    if not namespaced.startswith(MCP_NAMESPACE_PREFIX):
        return None
    rest = namespaced[len(MCP_NAMESPACE_PREFIX) :]
    parts = rest.split(_SEPARATOR, 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def is_namespaced_mcp_name(name: str) -> bool:
    """True when *name* is a well-formed namespaced MCP tool name."""
    return parse_namespaced_name(name) is not None
