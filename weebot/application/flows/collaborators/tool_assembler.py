"""ToolAssembler — assembles the tool collection for an execution step.

Extracted from PlanActFlow during architecture remediation (Step 2.2.2).
"""
from __future__ import annotations

from typing import Any, Optional

from weebot.application.flows.mcp_scope import apply_mcp_tool_scope
from weebot.application.flows.mcp_scope_config import McpScopeConfig
from weebot.domain.models.session import Session
from weebot.tools.tool_registry import RoleBasedToolRegistry


class ToolAssembler:
    """Assembles the tool collection for an execution step.

    Selects tools based on the current step type and MCP scope,
    applying dynamic MCP tool scoping when configured.
    """

    def __init__(
        self,
        registry: RoleBasedToolRegistry,
        mcp_bridge: Any | None = None,
        native_tool_selector: Any | None = None,
        llm: Any | None = None,
        agent_role: str = "admin",
        logger: Any | None = None,
    ) -> None:
        self._registry = registry
        self._mcp_bridge = mcp_bridge
        self._native_tool_selector = native_tool_selector
        self._llm = llm
        self._agent_role = agent_role
        self._logger = logger

    async def assemble(
        self,
        effective_prompt: str,
        tools: Any,
        executor: Any | None = None,
    ) -> Any:
        """Assemble and optionally scope tools for the current step.

        If MCP scoping is configured, applies dynamic tool scoping
        against the effective prompt and updates the executor's
        tool set if available.

        Args:
            effective_prompt: The current prompt to scope tools against.
            tools: The current tool collection (may be replaced by scoped set).
            executor: Optional executor agent to update with scoped tools.

        Returns:
            The (possibly scoped) tool collection.
        """
        if not self._mcp_bridge:
            return tools

        scope_config = McpScopeConfig(
            bridge=self._mcp_bridge,
            registry=self._registry,
            native_tool_selector=self._native_tool_selector,
            llm=self._llm,
            agent_role=self._agent_role,
            logger=self._logger,
        )
        scoped_tools = await apply_mcp_tool_scope(scope_config, effective_prompt)
        if scoped_tools is not None:
            tools = scoped_tools
            if executor is not None and hasattr(executor, "set_tools"):
                executor.set_tools(scoped_tools)
        return tools
