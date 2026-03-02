"""Factory for creating specialized agent instances in multi-agent workflows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from weebot.agent_core_v2 import AgentConfig, WeebotAgent
from weebot.core.agent_context import AgentContext
from weebot.tools.tool_registry import RoleBasedToolRegistry

if TYPE_CHECKING:
    from weebot.tools.base import ToolCollection

logger = logging.getLogger(__name__)


class AgentFactory:
    """Factory for spawning specialized agents with role-based tool access.

    Supports creating agent hierarchies up to 3 levels deep with:
    - Inherited settings from parent agents
    - Selective tool access based on role
    - Shared context for inter-agent communication
    """

    MAX_NESTING_LEVEL = 3

    def __init__(self, tool_registry: Optional[RoleBasedToolRegistry] = None) -> None:
        """Initialize the agent factory.

        Args:
            tool_registry: RoleBasedToolRegistry instance for tool access control.
                          If None, creates a default registry.
        """
        self.tool_registry = tool_registry or RoleBasedToolRegistry()
        self._agent_counter = 0

    async def spawn_agent(
        self,
        parent_agent_id: str,
        parent_context: AgentContext,
        role: str,
        tools_subset: Optional[List[str]] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None
    ) -> WeebotAgent:
        """Spawn a specialized child agent.

        Args:
            parent_agent_id: ID of the parent agent (for tracking relationships)
            parent_context: AgentContext from parent agent (for sharing data/events)
            role: Role/specialization of the child agent
                  ("researcher", "analyst", "automation", "custom")
            tools_subset: Optional explicit list of tools. If None, uses role-based access.
            config_overrides: Optional config overrides (budget, timeout, model, etc.)
            description: Optional description of the agent's purpose

        Returns:
            Spawned WeebotAgent instance configured with inherited + custom settings

        Raises:
            RuntimeError: If nesting level exceeds 3 or role is invalid
            ValueError: If config_overrides contain invalid values
        """
        # Validate nesting level
        if parent_context.nesting_level >= self.MAX_NESTING_LEVEL:
            raise RuntimeError(
                f"Cannot spawn child: parent is at max nesting level {parent_context.nesting_level}"
            )

        # Create child context
        child_context = AgentContext.create_child(parent_context, parent_agent_id, role)

        # Determine tools for this child
        if tools_subset is not None:
            # Explicit tool list provided
            allowed_tools = tools_subset
        else:
            # Use role-based tool registry
            allowed_tools = self.tool_registry.get_tools_for_role(role)
            logger.info(
                f"Agent {child_context.agent_id} (role={role}) assigned tools: {allowed_tools}"
            )

        # Validate tools exist (basic check)
        invalid_tools = [t for t in allowed_tools if not t]
        if invalid_tools:
            raise ValueError(f"Invalid tools: {invalid_tools}")

        # Create child config (inherited + overridden)
        # Note: In current codebase, we don't have parent agent reference,
        # so we create an independent config for the child
        child_config = AgentConfig(
            project_id=f"{parent_context.orchestrator_id}_{child_context.agent_id}",
            description=description or f"Child agent: {role}",
            auto_resume=True,
            notification_channels=[],
            daily_budget=(config_overrides or {}).get("daily_budget", 10.0),
            max_retries=(config_overrides or {}).get("max_retries", 3)
        )

        # Create agent instance
        agent = WeebotAgent(child_config)

        # Attach context to agent (custom attribute for multi-agent coordination)
        agent._context = child_context
        agent._parent_agent_id = parent_agent_id
        agent._role = role
        agent._allowed_tools = allowed_tools

        self._agent_counter += 1
        logger.info(
            f"Spawned agent {child_context.agent_id} (level {child_context.nesting_level}): "
            f"role={role}, tools={allowed_tools}"
        )

        # Publish event
        await child_context.publish_event(
            "agent_spawned",
            {
                "agent_id": child_context.agent_id,
                "role": role,
                "parent_id": parent_agent_id,
                "nesting_level": child_context.nesting_level,
                "tools": allowed_tools
            }
        )

        return agent

    async def spawn_orchestrator_agents(
        self,
        orchestrator_context: AgentContext,
        orchestrator_agent_id: str,
        agent_specs: List[Dict[str, Any]]
    ) -> Dict[str, WeebotAgent]:
        """Spawn multiple child agents from an orchestrator.

        Convenience method for spawning multiple specialized agents at once.

        Args:
            orchestrator_context: Context of the orchestrator agent
            orchestrator_agent_id: ID of the orchestrator agent
            agent_specs: List of dicts with keys:
                - role: str (required)
                - description: str (optional)
                - tools: List[str] (optional)
                - config_overrides: Dict (optional)

        Returns:
            Dictionary mapping agent role → WeebotAgent instance

        Example:
            agents = await factory.spawn_orchestrator_agents(
                context,
                "orchestrator_1",
                [
                    {
                        "role": "researcher",
                        "description": "Web research specialist",
                        "tools": ["web_search", "advanced_browser"]
                    },
                    {
                        "role": "analyst",
                        "description": "Data analysis specialist",
                        "tools": ["python_execute"]
                    }
                ]
            )
        """
        spawned = {}

        for spec in agent_specs:
            role = spec["role"]
            description = spec.get("description")
            tools = spec.get("tools")
            overrides = spec.get("config_overrides")

            agent = await self.spawn_agent(
                parent_agent_id=orchestrator_agent_id,
                parent_context=orchestrator_context,
                role=role,
                tools_subset=tools,
                config_overrides=overrides,
                description=description
            )

            spawned[role] = agent

        return spawned

    def validate_agent_context(self, agent: WeebotAgent) -> bool:
        """Check if an agent has valid context and role information.

        Args:
            agent: WeebotAgent instance to validate

        Returns:
            True if agent has valid context, False otherwise
        """
        return (
            hasattr(agent, "_context")
            and hasattr(agent, "_role")
            and hasattr(agent, "_allowed_tools")
            and agent._context is not None
        )

    def get_agent_info(self, agent: WeebotAgent) -> Dict[str, Any]:
        """Get metadata about an agent created by this factory.

        Args:
            agent: WeebotAgent instance

        Returns:
            Dictionary with agent metadata (id, role, context, tools, etc.)
        """
        if not self.validate_agent_context(agent):
            return {
                "is_multi_agent_enabled": False,
                "agent_id": agent.config.project_id
            }

        context: AgentContext = agent._context
        return {
            "is_multi_agent_enabled": True,
            "agent_id": context.agent_id,
            "orchestrator_id": context.orchestrator_id,
            "parent_id": context.parent_id,
            "role": agent._role,
            "nesting_level": context.nesting_level,
            "allowed_tools": agent._allowed_tools,
            "project_id": agent.config.project_id
        }

    async def validate_tool_access(self, agent: WeebotAgent, tool_name: str) -> bool:
        """Check if an agent has access to a specific tool.

        Args:
            agent: WeebotAgent instance
            tool_name: Name of the tool to check

        Returns:
            True if agent can access the tool, False otherwise
        """
        if not self.validate_agent_context(agent):
            # Non-multi-agent agent has access to all tools
            return True

        return tool_name in agent._allowed_tools
