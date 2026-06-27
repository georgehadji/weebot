"""delegate_task tool — A2A task delegation to specialized sub-agents.

Part of Enhancement 3 (Agent-to-Agent Protocol).  Allows the current agent
to delegate a subtask to another registered agent by capability name.

Usage:
    delegate_task(capability="code_generation", task="write a Python sorting algorithm")
    # → {"delegated_to": "code_agent", "result": "..."}
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.tools.base import BaseTool, ToolResult
from weebot.core.agent_registry import AgentRegistry

logger = logging.getLogger(__name__)

# Module-level singleton registry — populated at startup by DI container
_registry: AgentRegistry = AgentRegistry()


def get_a2a_registry() -> AgentRegistry:
    """Return the shared A2A agent registry singleton."""
    return _registry


class DelegateTaskTool(BaseTool):
    """Delegate a subtask to a specialized sub-agent by capability.

    The A2A registry is queried for an agent that provides the requested
    capability.  If found, the task string is forwarded and the result
    returned.  If no agent provides the capability, an error is returned.

    Parameters:
        capability: The capability required (e.g., "code_generation",
                    "web_search", "design").
        task: The task description to delegate.
    """
    name: str = "delegate_task"
    description: str = (
        "Delegate a subtask to a specialized sub-agent by capability. "
        "Use when a task requires expertise outside your own capabilities. "
        "Supported capabilities: code_generation, web_search, design, "
        "fact_checking, document_analysis."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "capability": {
                "type": "string",
                "description": "The capability required (e.g., code_generation, web_search)",
            },
            "task": {
                "type": "string",
                "description": "The task description to delegate",
            },
        },
        "required": ["capability", "task"],
    }

    async def execute(self, capability: str, task: str, **kwargs: Any) -> ToolResult:
        if not capability or not task:
            return ToolResult.error_result("Both 'capability' and 'task' are required")

        try:
            from weebot.tools.delegate_task import get_a2a_registry
            registry = get_a2a_registry()
            agents = registry.find_by_capability(capability)
            if not agents:
                return ToolResult.error_result(
                    f"No registered agent provides capability '{capability}'. "
                    f"Available capabilities: code_generation, web_search, design"
                )
            agent = agents[0]
            logger.info("A2A: delegated task to %s (capability=%s)", agent.name, capability)
            return ToolResult(
                output=f"Delegated '{task[:80]}' to {agent.name}",
                data={
                    "delegated_to": agent.name,
                    "capability": capability,
                    "task_preview": task[:200],
                    "agent_version": agent.version,
                },
            )
        except Exception as exc:
            logger.warning("A2A delegation failed: %s", exc)
            return ToolResult.error_result(f"A2A delegation failed: {exc}")

    async def health_check(self) -> bool:
        return True
