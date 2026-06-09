"""Tests for Phase 7: TreeOfThoughtsScorer."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.tree_of_thoughts_scorer import (
    TreeOfThoughtsScorer,
    ScoredCandidate,
)


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.mark.asyncio
async def test_generate_candidates_returns_list(mock_llm):
    """generate_candidates returns a list of strings."""
    mock_llm.chat.return_value = MagicMock(
        content='{"candidates": ["Approach A", "Approach B", "Approach C"]}'
    )
    scorer = TreeOfThoughtsScorer(llm=mock_llm, num_candidates=3)
    candidates = await scorer.generate_candidates("Do X", "Failed because Y")
    assert len(candidates) == 3
    assert "Approach A" in candidates


@pytest.mark.asyncio
async def test_generate_candidates_handles_parse_failure(mock_llm):
    """Malformed response returns fallback single candidate."""
    mock_llm.chat.return_value = MagicMock(content="not valid json")
    scorer = TreeOfThoughtsScorer(llm=mock_llm)
    candidates = await scorer.generate_candidates("Do X", "Failed")
    assert len(candidates) >= 1


@pytest.mark.asyncio
async def test_generate_candidates_handles_timeout(mock_llm):
    """Timeout returns fallback candidate."""
    import asyncio
    mock_llm.chat.side_effect = asyncio.TimeoutError()
    scorer = TreeOfThoughtsScorer(llm=mock_llm)
    candidates = await scorer.generate_candidates("Do X", "Failed")
    assert len(candidates) >= 1


@pytest.mark.asyncio
async def test_score_candidate_returns_scored_candidate(mock_llm):
    """score_candidate returns a ScoredCandidate with scores."""
    mock_llm.chat.return_value = MagicMock(
        content='{"novelty": 4, "feasibility": 3, "specificity": 5}'
    )
    scorer = TreeOfThoughtsScorer(llm=mock_llm)
    scored = await scorer.score_candidate("Approach A", "Original step")
    assert isinstance(scored, ScoredCandidate)
    assert scored.novelty == 4
    assert scored.feasibility == 3
    assert scored.specificity == 5
    assert scored.aggregate == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_score_candidate_handles_parse_failure(mock_llm):
    """Parse failure returns default-scored candidate."""
    mock_llm.chat.return_value = MagicMock(content="bad json")
    scorer = TreeOfThoughtsScorer(llm=mock_llm)
    scored = await scorer.score_candidate("Approach A", "Original")
    assert isinstance(scored, ScoredCandidate)
    assert scored.aggregate == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_best_candidate_returns_string(mock_llm):
    """best_candidate returns a non-empty string."""
    mock_llm.chat.return_value = MagicMock(
        content='{"candidates": ["Approach A", "Approach B"]}'
    )
    scorer = TreeOfThoughtsScorer(llm=mock_llm, num_candidates=2)
    best = await scorer.best_candidate("Do X", "Failed")
    assert isinstance(best, str)
    assert len(best) > 0


def test_scored_candidate_auto_aggregate():
    """ScoredCandidate auto-computes aggregate."""
    c = ScoredCandidate(
        description="Test", novelty=3, feasibility=4, specificity=5,
    )
    assert c.aggregate == pytest.approx(4.0)


def test_scored_candidate_defaults():
    """ScoredCandidate has default scores of 1."""
    c = ScoredCandidate(description="Test")
    assert c.novelty == 1
    assert c.feasibility == 1
    assert c.specificity == 1
    assert c.aggregate == pytest.approx(1.0)
