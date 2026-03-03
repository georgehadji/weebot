"""Tests verifying fixes for agent_factory.py validation bugs.

Bug #3a: Tool name validation only caught empty strings — typos like "bash_tol" passed.
Bug #3b: Duplicate roles in spawn_orchestrator_agents silently overwrote earlier agents.
"""
from __future__ import annotations

import pytest

from weebot.core.agent_context import AgentContext
from weebot.core.agent_factory import AgentFactory
from weebot.tools.tool_registry import RoleBasedToolRegistry


# ---------------------------------------------------------------------------
# Bug #3a: Tool name validation
# ---------------------------------------------------------------------------

class TestToolNameValidation:
    """spawn_agent must reject typos in explicitly provided tools_subset."""

    @pytest.mark.asyncio
    async def test_valid_tool_names_accepted(self):
        """Correct tool names in tools_subset must be accepted without error."""
        factory = AgentFactory()
        ctx = AgentContext.create_orchestrator()

        agent = await factory.spawn_agent(
            parent_agent_id=ctx.agent_id,
            parent_context=ctx,
            role="analyst",
            tools_subset=["bash", "python_execute"],
        )
        assert agent._allowed_tools == ["bash", "python_execute"]

    @pytest.mark.asyncio
    async def test_typo_in_tools_subset_raises_at_spawn(self):
        """A typo like 'bash_tol' must raise ValueError at spawn, not at runtime."""
        factory = AgentFactory()
        ctx = AgentContext.create_orchestrator()

        with pytest.raises(ValueError, match="Unknown tool names"):
            await factory.spawn_agent(
                parent_agent_id=ctx.agent_id,
                parent_context=ctx,
                role="analyst",
                tools_subset=["python_execute", "bash_tol"],  # typo: "bash_tol"
            )

    @pytest.mark.asyncio
    async def test_empty_string_in_tools_subset_raises(self):
        """Empty string in tools_subset must be rejected."""
        factory = AgentFactory()
        ctx = AgentContext.create_orchestrator()

        with pytest.raises(ValueError, match="Empty/None"):
            await factory.spawn_agent(
                parent_agent_id=ctx.agent_id,
                parent_context=ctx,
                role="analyst",
                tools_subset=["python_execute", ""],
            )

    @pytest.mark.asyncio
    async def test_none_in_tools_subset_raises(self):
        """None value in tools_subset must be rejected."""
        factory = AgentFactory()
        ctx = AgentContext.create_orchestrator()

        with pytest.raises((ValueError, TypeError)):
            await factory.spawn_agent(
                parent_agent_id=ctx.agent_id,
                parent_context=ctx,
                role="analyst",
                tools_subset=["python_execute", None],
            )

    @pytest.mark.asyncio
    async def test_role_based_tools_bypass_class_map_validation(self):
        """Role-based tools (no explicit tools_subset) bypass strict class-map validation.
        The registry is the authoritative source for role-based tools."""
        # Create a registry with a custom role that has a "soft" tool name
        custom_registry = RoleBasedToolRegistry(
            role_mappings={"tester": ["bash", "python_execute"]}
        )
        factory = AgentFactory(tool_registry=custom_registry)
        ctx = AgentContext.create_orchestrator()

        # Spawning without tools_subset uses registry — should not validate against class map
        agent = await factory.spawn_agent(
            parent_agent_id=ctx.agent_id,
            parent_context=ctx,
            role="tester",
            tools_subset=None,  # explicit: use registry
        )
        assert "bash" in agent._allowed_tools


# ---------------------------------------------------------------------------
# Bug #3b: Duplicate role detection
# ---------------------------------------------------------------------------

class TestDuplicateRoleDetection:
    """spawn_orchestrator_agents must reject duplicate roles before spawning any agent."""

    @pytest.mark.asyncio
    async def test_duplicate_role_raises_before_spawning(self):
        """When two specs have the same role, ValueError is raised immediately."""
        factory = AgentFactory()
        ctx = AgentContext.create_orchestrator()

        with pytest.raises(ValueError, match="Duplicate roles"):
            await factory.spawn_orchestrator_agents(
                orchestrator_context=ctx,
                orchestrator_agent_id=ctx.agent_id,
                agent_specs=[
                    {"role": "researcher", "tools": ["web_search"]},
                    {"role": "analyst", "tools": ["python_execute"]},
                    {"role": "researcher", "tools": ["web_search"]},  # duplicate!
                ],
            )

    @pytest.mark.asyncio
    async def test_unique_roles_spawn_successfully(self):
        """All-unique roles should produce a populated spawned dict."""
        factory = AgentFactory()
        ctx = AgentContext.create_orchestrator()

        spawned = await factory.spawn_orchestrator_agents(
            orchestrator_context=ctx,
            orchestrator_agent_id=ctx.agent_id,
            agent_specs=[
                {"role": "researcher", "tools": ["web_search"]},
                {"role": "analyst", "tools": ["python_execute"]},
            ],
        )
        assert set(spawned.keys()) == {"researcher", "analyst"}

    @pytest.mark.asyncio
    async def test_error_message_names_duplicated_roles(self):
        """Error message should identify WHICH roles are duplicated."""
        factory = AgentFactory()
        ctx = AgentContext.create_orchestrator()

        with pytest.raises(ValueError) as exc_info:
            await factory.spawn_orchestrator_agents(
                orchestrator_context=ctx,
                orchestrator_agent_id=ctx.agent_id,
                agent_specs=[
                    {"role": "analyst", "tools": ["python_execute"]},
                    {"role": "analyst", "tools": ["bash"]},
                ],
            )
        assert "analyst" in str(exc_info.value)
