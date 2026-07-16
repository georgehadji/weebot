"""Typed configuration contract for MCP tool scoping.

``McpScopeConfig`` is a small Application-layer dataclass that exposes exactly
the dependencies ``apply_mcp_tool_scope`` needs, replacing the previous
untyped ``PlanActFlow`` duck-typing via ``getattr``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.tools.tool_registry import RoleBasedToolRegistry


@dataclass
class McpScopeConfig:
    """Minimal, typed contract passed from PlanActFlow to MCP scoping."""

    bridge: Any | None = None
    registry: RoleBasedToolRegistry | None = None
    native_tool_selector: Any | None = None
    llm: LLMPort | None = None
    agent_role: str = "admin"
    logger: Any | None = None
