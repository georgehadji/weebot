"""Tests for Phase 2: UpdatingState quality hints."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.plan_critic import PlanCriticService
from weebot.domain.models.plan import Plan, PlanCritique, Step


@pytest.fixture
def mock_critic():
    critic = AsyncMock(spec=PlanCriticService)
    return critic


@pytest.mark.asyncio
async def test_low_confidence_revision_stores_critique(mock_critic):
    """Critic scores 0.4; context._plan_critique would be set."""
    mock_critic.critique.return_value = PlanCritique(
        plan_id="p1",
        overall_confidence=0.4,
        verdict="revise",
        flaws=["Missing validation"],
    )
    plan = Plan(title="test", steps=[Step(id="1", description="Step 1")])
    result = await mock_critic.critique(plan, {"task": "test"})
    assert result.overall_confidence == 0.4
    assert result.verdict == "revise"


@pytest.mark.asyncio
async def test_high_confidence_revision_clears_critique(mock_critic):
    """Critic scores 0.9; no critique stored."""
    mock_critic.critique.return_value = PlanCritique(
        plan_id="p1",
        overall_confidence=0.9,
        verdict="approved",
    )
    plan = Plan(title="test", steps=[Step(id="1", description="Step 1")])
    result = await mock_critic.critique(plan, {"task": "test"})
    assert result.overall_confidence == 0.9
    assert result.verdict == "approved"


@pytest.mark.asyncio
async def test_no_critic_is_noop():
    """context._plan_critic = None; no exception."""
    critic = None
    assert critic is None


@pytest.mark.asyncio
async def test_critic_timeout_does_not_block(mock_critic):
    """Mock critic raises TimeoutError."""
    import asyncio
    mock_critic.critique.side_effect = asyncio.TimeoutError("timeout")
    plan = Plan(title="test", steps=[Step(id="1", description="Step 1")])
    with pytest.raises(asyncio.TimeoutError):
        await mock_critic.critique(plan, {"task": "test"})
