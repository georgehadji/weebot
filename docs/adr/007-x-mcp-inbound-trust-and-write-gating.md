# ADR-007: X (Twitter) MCP — Inbound Trust and Write Gating

**Date:** 2026-06-30
**Status:** Approved
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

weebot agents need to search X (Twitter) posts, user profiles, trends, and
optionally publish content through X's hosted MCP servers.  X content is
**external** — the model has no control over what the remote server returns
— making it a prompt-injection vector, exactly like web search results,
email, or browser automation output.

Additionally, write operations (bookmarks, article publish, create/delete)
could be triggered autonomously by a compromised or misdirected agent unless
properly gated.

---

## Decision

### 1. X content is untrusted — all MCP output is fenced

Every namespaced MCP tool (``mcp__<server>__<tool>``) is classified as
untrusted output.  The ``is_untrusted_tool()`` function in
``weebot/core/trust_boundary.py`` prefix-matches ``mcp__`` in addition to
the existing literal-name set.  This means:

- ``mcp__xapi__search_posts`` → untrusted
- ``mcp__x_docs__search_x`` → untrusted
- ``mcp__stripe__create_payment`` → untrusted

All MCP tool results are wrapped in ``⟦UNTRUSTED_DATA …⟧`` delimiters with
the preamble warning before entering the LLM prompt.

### 2. Writes are admin-only + restricted tier

Write-bearing MCP tools (those matching configurable ``write_tools`` glob
patterns) register only to the ``admin`` role at ``restricted`` tier.
Autonomous roles (``automation``, ``researcher``, ``coder``) cannot call them.

Read tools register to all four roles at ``controlled`` tier as before.

### 3. Secrets live in environment variables, never in config files

MCP server configs use ``${VAR}`` syntax that is expanded by
``config_loader.expand_env()`` at load time.  Unset vars cause a clear
``ConfigError`` at startup rather than silently sending literal ``${VAR}``
tokens.

### 4. Feature flag gates the entire integration

``WEEBOT_ENABLE_X_MCP`` (default off) controls whether the DI factory loads
any X MCP server configuration.  This mirrors the ``WEEBOT_ENABLE_ATOMIC_MAIL``
pattern.

### 5. X OAuth is delegated to xurl, not implemented in weebot

weebot does not implement the X PKCE flow.  Instead, the ``mcp login`` CLI
command prints instructions for running ``xurl auth oauth2 --headless``
out-of-band.  The resulting token cache in ``~/.xurl`` is reused on
subsequent stdio spawns.

---

## Consequences

### Positive

- Prompt-injection via X posts is prevented by the trust-boundary fence.
- Write operations cannot be triggered by automation/researcher/coder roles.
- Secrets never appear in config files or logs.
- Out-of-band OAuth means no browser dependency on the headless server.

### Negative

- Path B (OAuth writes) requires an extra manual ``xurl auth`` step.
- The ``mcp__`` prefix catch in ``is_untrusted_tool()`` fences *all* MCP
  tools, including internal ones that might eventually want trusted status.
  A future ADR could add a ``trusted_mcp_tools`` allowlist if needed.
- Config templates are JSON files that must be copied into place by the
  operator (no ``mcp import-template`` command yet — see Future Work).

---

## Related

- ADR-006: Atomic Mail — inbound trust boundary (same pattern, different source)
- ``weebot/core/trust_boundary.py`` — ``is_untrusted_tool()`` implementation
- ``weebot/infrastructure/mcp/config_loader.py`` — ``expand_env()``
- ``weebot/domain/models/mcp.py`` — ``MCPToolFilterConfig.write_tools``
- ``weebot/application/services/mcp_tool_registry_bridge.py`` — write gating
- ``weebot/config/templates/mcp/mcp_servers.x-*.json`` — config templates
