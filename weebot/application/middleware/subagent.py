"""SubAgentMiddleware — single `task` tool wrapping SubAgentFactoryPort.

Exposes sub-agent dispatch as a single `task` tool instead of three separate
tools (DispatchAgentsTool, SwarmTool, HyperAgentFlow). The agent calls
`task(description="...", subagent_type="coder")` and the middleware compiles
and invokes the sub-agent graph inline, returning the result as a tool message.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.application.middleware.base import (
    Middleware,
    MiddlewareRequest,
    ToolCallResult,
)

logger = logging.getLogger(__name__)


_TASK_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "task",
        "description": (
            "Delegate a sub-task to a specialized sub-agent. "
            "Use when the task has clearly separable concerns that another "
            "agent role could handle better. Returns the sub-agent's result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What the sub-agent should do. Be specific about inputs and expected outputs.",
                },
                "subagent_type": {
                    "type": "string",
                    "enum": ["coder", "researcher", "analyst", "reviewer", "automation", "designer"],
                    "description": "Which role of sub-agent to dispatch.",
                },
            },
            "required": ["description", "subagent_type"],
        },
    },
}


class SubAgentMiddleware(Middleware):
    """Injects a `task` tool and handles sub-agent dispatch via SubAgentFactoryPort.

    Args:
        sub_factory: SubAgentFactoryPort instance. If None, the tool is injected
                     but returns an error on use.
    """

    def __init__(self, sub_factory: Optional[Any] = None) -> None:
        self._sub_factory = sub_factory

    def name(self) -> str:
        return "SubAgentMiddleware"

    async def before_request(
        self,
        request: MiddlewareRequest,
        state: dict[str, Any],
    ) -> tuple[MiddlewareRequest, dict[str, Any]]:
        """Inject the `task` tool into the tool list."""
        tools = list(request.tools)
        # Check if task tool is already present
        if not any(
            t.get("function", {}).get("name") == "task"
            for t in tools
        ):
            tools.append(_TASK_TOOL_DEFINITION)
        request.tools = tools
        return request, state

    async def after_tool_call(
        self,
        result: ToolCallResult,
        state: dict[str, Any],
    ) -> tuple[ToolCallResult, dict[str, Any]]:
        """Intercept `task` tool calls and dispatch to SubAgentFactoryPort."""
        if result.tool_name != "task" or self._sub_factory is None:
            return result, state

        try:
            desc = result.arguments.get("description", "")
            sub_type = result.arguments.get("subagent_type", "coder")

            from weebot.domain.models.sub_agent import (
                AgentTier,
                DispatchStrategy,
                SubAgentRole,
                SubAgentSpec,
            )

            role_map = {
                "coder": SubAgentRole.CODER,
                "researcher": SubAgentRole.RESEARCHER,
                "analyst": SubAgentRole.ANALYST,
                "reviewer": SubAgentRole.REVIEWER,
                "automation": SubAgentRole.AUTOMATION,
                "designer": SubAgentRole.DESIGNER,
            }

            spec = SubAgentSpec(
                role=role_map.get(sub_type, SubAgentRole.CODER),
                description=desc[:200],
                prompt=desc,
                tier=AgentTier.BUDGET,
                strategy=DispatchStrategy.PARALLEL,
                max_tool_calls=10,
            )

            sub_result = await self._sub_factory.spawn(spec)

            result.output = sub_result.summary or "(no output)"
            result.is_error = not sub_result.is_success
            if not sub_result.is_success:
                result.error = sub_result.error or "Sub-agent failed"

        except Exception as exc:
            logger.warning("SubAgentMiddleware task failed: %s", exc)
            result.output = ""
            result.error = f"Sub-agent dispatch failed: {exc}"
            result.is_error = True

        return result, state
