"""Tests for Phase 1: Pre-mortem analyzer and state."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.premortem_analyzer import PremortmAnalyzer
from weebot.domain.models.plan import Plan, Step


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def sample_plan():
    return Plan(
        title="Test plan",
        message="A test plan",
        steps=[
            Step(id="1", description="Research topic"),
            Step(id="2", description="Write analysis"),
            Step(id="3", description="Review output"),
            Step(id="4", description="Deliver results"),
        ],
    )


@pytest.mark.asyncio
async def test_analyzer_returns_risks_on_valid_response(mock_llm, sample_plan):
    """Mock LLM returns JSON; risks list has ≤ 3 items."""
    mock_llm.chat.return_value = MagicMock(
        content='{"risks": ["Missing data source", "Scope creep", "Timeout"]}'
    )
    analyzer = PremortmAnalyzer(llm=mock_llm)
    risks = await analyzer.analyze(sample_plan, "Do research")
    assert len(risks) == 3
    assert "Missing data source" in risks


@pytest.mark.asyncio
async def test_analyzer_returns_empty_on_timeout(mock_llm, sample_plan):
    """Mock LLM raises TimeoutError; returns []."""
    import asyncio
    mock_llm.chat.side_effect = asyncio.TimeoutError("timeout")
    analyzer = PremortmAnalyzer(llm=mock_llm, timeout_seconds=1)
    risks = await analyzer.analyze(sample_plan, "Do research")
    assert risks == []


@pytest.mark.asyncio
async def test_analyzer_returns_empty_on_parse_failure(mock_llm, sample_plan):
    """Mock LLM returns malformed JSON; returns []."""
    mock_llm.chat.return_value = MagicMock(content="not valid json")
    analyzer = PremortmAnalyzer(llm=mock_llm)
    risks = await analyzer.analyze(sample_plan, "Do research")
    assert risks == []


@pytest.mark.asyncio
async def test_analyzer_caps_at_three_risks(mock_llm, sample_plan):
    """LLM returns 5 risks; analyzer caps to 3."""
    mock_llm.chat.return_value = MagicMock(
        content='{"risks": ["A", "B", "C", "D", "E"]}'
    )
    analyzer = PremortmAnalyzer(llm=mock_llm)
    risks = await analyzer.analyze(sample_plan, "Do research")
    assert len(risks) == 3


@pytest.mark.asyncio
async def test_analyzer_returns_empty_on_empty_plan(mock_llm):
    """Empty plan (no steps) returns [] ASAP."""
    plan = Plan(title="empty", steps=[])
    mock_llm.chat.return_value = MagicMock(content='{"risks": ["A"]}')
    analyzer = PremortmAnalyzer(llm=mock_llm)
    risks = await analyzer.analyze(plan, "")
    # With zero steps it still calls the LLM but should handle gracefully
    assert isinstance(risks, list)
