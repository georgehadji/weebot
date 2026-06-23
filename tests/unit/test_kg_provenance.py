"""Tests for KG provenance — commitment and opportunity nodes."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.commitment_engine import CommitmentEngine
from weebot.domain.models.commitment import Commitment, CommitmentStatus


class TestCommitmentKGProvenance:
    """CommitmentEngine creates KG nodes when knowledge_graph is provided."""

    @pytest.fixture
    def engine(self):
        repo = MagicMock()
        repo.list_commitments = AsyncMock(return_value=[
            Commitment(
                id="cmt-1", promise_text="check back in 2 hours",
                context="", source_session_id="sess-1",
                status=CommitmentStatus.PENDING,
            ),
        ])
        repo.update_commitment_status = AsyncMock(return_value=True)
        kg = MagicMock()
        kg.query = AsyncMock(return_value=[])
        kg.discover_node = AsyncMock()
        kg.relate_nodes = AsyncMock()
        return CommitmentEngine(state_repo=repo, knowledge_graph=kg)

    async def test_heartbeat_creates_kg_nodes(self, engine):
        stats = await engine.heartbeat()
        # Should have attempted KG node creation
        assert engine._kg.discover_node.called
        assert engine._kg.relate_nodes.called

    async def test_no_kg_skips_provenance(self):
        repo = MagicMock()
        repo.list_commitments = AsyncMock(return_value=[
            Commitment(
                id="cmt-1", promise_text="test",
                context="", source_session_id="sess-1",
                status=CommitmentStatus.PENDING,
            ),
        ])
        repo.update_commitment_status = AsyncMock(return_value=True)
        engine = CommitmentEngine(state_repo=repo, knowledge_graph=None)
        stats = await engine.heartbeat()
        # When KG is None, no discover_node should be attempted
        assert stats["checked"] == 1
        assert engine._kg is None


class TestOpportunityKGProvenance:
    """OpportunityEngine creates KG nodes when knowledge_graph is provided."""

    @pytest.fixture
    def engine(self):
        from weebot.application.services.opportunity_engine import OpportunityEngine
        kg = MagicMock()
        kg.query = AsyncMock(return_value=[])
        kg.discover_node = AsyncMock()
        return OpportunityEngine(
            knowledge_graph=kg,
            fts5_search=MagicMock(),
            state_repo=MagicMock(),
        )

    @pytest.fixture
    def mock_scan_result(self):
        from weebot.domain.models.opportunity import OpportunityProposal
        return [
            OpportunityProposal(
                id="opp-1",
                prompt="Research competitor pricing",
                source="knowledge_gap",
                confidence=0.85,
            ),
        ]

    @pytest.mark.asyncio
    async def test_scan_creates_kg_nodes(self, engine, mock_scan_result):
        # Patch internal scan methods to return the mock proposal
        engine._scan_knowledge_gaps = AsyncMock(return_value=mock_scan_result)
        engine._scan_recurring_patterns = AsyncMock(return_value=[])
        proposals = await engine.scan()
        assert engine._kg.discover_node.called
