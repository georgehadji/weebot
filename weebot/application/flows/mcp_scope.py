"""Scoped MCP tool aggregation helper for PlanActFlow.

Extracted from ``plan_act_flow.py`` to keep that module under the architecture
fitness line-count limit and to isolate the H1 scoping concern.

This version is non-mutating: it queries the bridge for the relevant external
tool subset and builds a fresh ``ToolCollection`` from native tools + those
scoped external tools, without altering the shared registry.
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.flows.mcp_scope_config import McpScopeConfig

logger = logging.getLogger(__name__)

# Namespace prefix used by MCPToolRegistryBridge for external MCP tools.
_MCP_TOOL_PREFIX = "mcp__"


async def apply_mcp_tool_scope(scope_config: McpScopeConfig, prompt: str) -> Any:
    """Build a scoped ToolCollection for *prompt* without mutating the registry.

    Args:
        scope_config: Typed configuration exposing the bridge, registry,
            native-tool selector, LLM port, agent role, and logger.
        prompt: The effective user prompt used for relevance scoring.

    Returns:
        The rebuilt ``ToolCollection`` for the scoped turn, or ``None`` if
        scoping is unavailable or fails.
    """
    bridge = scope_config.bridge
    registry = scope_config.registry
    stdlib_logger = scope_config.logger or logger

    if bridge is None or registry is None:
        return None

    if not hasattr(bridge, "select_for_query"):
        return None

    try:
        scoped_names = await bridge.select_for_query(prompt)
    except Exception as exc:
        stdlib_logger.warning(
            "MCP tool selection failed for prompt: %s — continuing with full tool set",
            exc,
            exc_info=True,
        )
        return None

    role = scope_config.agent_role or "admin"
    try:
        current_names = registry.get_tools_for_role(role)
    except ValueError:
        return None

    native_names = [name for name in current_names if not name.startswith(_MCP_TOOL_PREFIX)]

    # ── Optional native-tool scoping (Fix 3) ────────────────────────────
    selector = scope_config.native_tool_selector
    if selector is not None and hasattr(selector, "select_for_query"):
        try:
            selected_native = await selector.select_for_query(prompt)
        except Exception as exc:
            stdlib_logger.debug("Native tool selection failed: %s", exc)
            selected_native = []
        # Only keep native tools that are both authorized for the role and
        # selected by the retrieval service.
        authorized_selected = [name for name in selected_native if name in native_names]
        if authorized_selected:
            native_names = authorized_selected
            stdlib_logger.debug(
                "Native tool scoping: %d tools selected for role %r",
                len(native_names), role,
            )

    scoped_tool_names = native_names + list(scoped_names)

    try:
        scoped_tools = registry.create_tool_collection_from_names(
            scoped_tool_names,
            llm_port=scope_config.llm,
        )
    except Exception as exc:
        stdlib_logger.warning(
            "Failed to rebuild tool collection after MCP selection: %s",
            exc,
            exc_info=True,
        )
        return None

    stdlib_logger.info(
        "MCP scoped aggregation: %d external tools selected for role %r; "
        "tool collection now has %d tools",
        len(scoped_names),
        role,
        len(scoped_tools) if scoped_tools else 0,
    )
    return scoped_tools
