"""Tests for AgentFactory."""

import pytest

from weebot.core.agent_factory import AgentFactory
from weebot.core.agent_context import AgentContext
from weebot.tools.tool_registry import RoleBasedToolRegistry


class TestAgentFactory:
    """Test cases for multi-agent spawning with role-based tool access."""

    @pytest.mark.asyncio
    async def test_spawn_agent_with_role(self):
        """Test spawning an agent with a specific role."""
        factory = AgentFactory()
        orchestrator_context = AgentContext.create_orchestrator()

        agent = await factory.spawn_agent(
            parent_agent_id=orchestrator_context.agent_id,
            parent_context=orchestrator_context,
            role="researcher",
            description="Research specialist"
        )

        assert agent is not None
        assert factory.validate_agent_context(agent)
        info = factory.get_agent_info(agent)
        assert info["role"] == "researcher"
        assert info["nesting_level"] == 2

    @pytest.mark.asyncio
    async def test_spawn_agent_invalid_role_raises_error(self):
        """Test that invalid role raises error."""
        factory = AgentFactory()
        context = AgentContext.create_orchestrator()

        with pytest.raises(ValueError) as exc_info:
            await factory.spawn_agent(
                parent_agent_id=context.agent_id,
                parent_context=context,
                role="nonexistent_role",
            )

        assert "Unknown role" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_spawn_agent_nesting_limit(self):
        """Test that nesting level 3 is the maximum."""
        factory = AgentFactory()
        orchestrator = AgentContext.create_orchestrator()

        # Spawn level 2
        agent_l2 = await factory.spawn_agent(
            parent_agent_id=orchestrator.agent_id,
            parent_context=orchestrator,
            role="analyst"
        )
        context_l2 = agent_l2._context

        # Spawn level 3
        agent_l3 = await factory.spawn_agent(
            parent_agent_id=agent_l2.config.project_id,
            parent_context=context_l2,
            role="automation"
        )
        context_l3 = agent_l3._context

        # Try to spawn level 4 (should fail)
        with pytest.raises(RuntimeError) as exc_info:
            await factory.spawn_agent(
                parent_agent_id=agent_l3.config.project_id,
                parent_context=context_l3,
                role="researcher"
            )

        assert "max nesting level" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_spawn_orchestrator_agents_multiple(self):
        """Test spawning multiple agents from orchestrator."""
        factory = AgentFactory()
        context = AgentContext.create_orchestrator()

        specs = [
            {"role": "researcher", "description": "Research specialist"},
            {"role": "analyst", "description": "Analysis specialist"},
            {"role": "automation", "description": "Automation specialist"}
        ]

        agents = await factory.spawn_orchestrator_agents(
            context,
            context.agent_id,
            specs
        )

        assert len(agents) == 3
        assert "researcher" in agents
        assert "analyst" in agents
        assert "automation" in agents

        # Verify each agent has correct role
        assert factory.get_agent_info(agents["researcher"])["role"] == "researcher"
        assert factory.get_agent_info(agents["analyst"])["role"] == "analyst"

    @pytest.mark.asyncio
    async def test_tool_access_validation(self):
        """Test that spawned agents have correct tool access."""
        factory = AgentFactory()
        context = AgentContext.create_orchestrator()

        # Spawn researcher
        researcher = await factory.spawn_agent(
            parent_agent_id=context.agent_id,
            parent_context=context,
            role="researcher"
        )

        # Spawn analyst
        analyst = await factory.spawn_agent(
            parent_agent_id=context.agent_id,
            parent_context=context,
            role="analyst"
        )

        # Researcher should have web_search
        assert await factory.validate_tool_access(researcher, "web_search") is True

        # Analyst should have python_tool
        assert await factory.validate_tool_access(analyst, "python_tool") is True

        # Researcher should NOT have python_tool
        assert await factory.validate_tool_access(researcher, "python_tool") is False

        # Analyst should NOT have web_search
        assert await factory.validate_tool_access(analyst, "web_search") is False
