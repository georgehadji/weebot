"""Tests for Phase 6: ParallelAgentRouter."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.parallel_agent_router import ParallelAgentRouter
from weebot.domain.models.task_route import TaskCategory, TaskComplexity, TaskRoute


@pytest.fixture
def mock_fallback():
    fb = AsyncMock()
    fb.route.return_value = TaskRoute(
        category=TaskCategory.RESEARCH,
        complexity=TaskComplexity.HIGH,
        flow_type="plan_act",
        tool_restriction="admin_role",
        confidence=0.8,
    )
    return fb


@pytest.fixture
def mock_sub_factory():
    factory = AsyncMock()

    async def fake_sub_agent(task, max_steps=10):
        yield MagicMock(type="message", message="Sub-agent result")

    factory.create_sub_agent = fake_sub_agent
    return factory


@pytest.mark.asyncio
async def test_simple_task_uses_fallback(mock_fallback):
    """Simple complexity falls back to base router (no parallel)."""
    mock_fallback.route.return_value = TaskRoute(
        category=TaskCategory.CASUAL,
        complexity=TaskComplexity.LOW,
        flow_type="plan_act",
        tool_restriction="admin_role",
        confidence=0.9,
    )
    router = ParallelAgentRouter(fallback=mock_fallback, sub_agent_factory=None)
    route = await router.route("Hello")
    assert route.complexity == TaskComplexity.LOW
    assert not hasattr(route, "parallel_subtasks") or not route.parallel_subtasks


@pytest.mark.asyncio
async def test_complex_task_without_factory_falls_back(mock_fallback):
    """Complex task without sub-agent factory uses fallback."""
    router = ParallelAgentRouter(fallback=mock_fallback, sub_agent_factory=None)
    route = await router.route("Research quantum computing")
    assert route.category == TaskCategory.RESEARCH
    assert route.complexity == TaskComplexity.HIGH


@pytest.mark.asyncio
async def test_complex_task_with_factory_returns_route(mock_fallback, mock_sub_factory):
    """Complex task with factory returns a TaskRoute."""
    router = ParallelAgentRouter(
        fallback=mock_fallback,
        sub_agent_factory=mock_sub_factory,
        max_parallel=2,
    )
    route = await router.route("Analyze large dataset")
    assert route is not None
    assert route.complexity == TaskComplexity.HIGH


@pytest.mark.asyncio
async def test_refresh_calls_fallback(mock_fallback):
    """refresh() delegates to fallback."""
    router = ParallelAgentRouter(fallback=mock_fallback)
    await router.refresh()
    mock_fallback.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_sub_factory_failure_falls_back(mock_fallback):
    """Sub-agent factory raising exception -> returns base route."""
    router = ParallelAgentRouter(
        fallback=mock_fallback,
        sub_agent_factory=AsyncMock(),  # factory without create_sub_agent
        max_parallel=2,
    )
    # Should not crash
    route = await router.route("Complex task")
    assert route is not None
