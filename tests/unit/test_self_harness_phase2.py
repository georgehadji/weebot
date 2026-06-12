"""Phase 2 tests: FailureSignature domain models, CQRS commands, handlers, and repository."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. Domain Models ──────────────────────────────────────────────────────

class TestFailureSignature:
    def test_defaults(self):
        from weebot.domain.models.failure_signature import FailureSignature
        sig = FailureSignature(session_id="s1", task_id="t1", terminal_cause="timeout",
                                agent_behavior="retry_loop", mechanism="unproductive_repetition")
        assert sig.session_id == "s1"
        assert sig.terminal_cause == "timeout"
        assert sig.extracted_at is not None
        assert sig.cluster_key == ("timeout", "retry_loop", "unproductive_repetition")

    def test_cluster_key_matches(self):
        from weebot.domain.models.failure_signature import FailureSignature
        a = FailureSignature(session_id="s1", task_id="t1", terminal_cause="timeout",
                              agent_behavior="retry_loop", mechanism="unproductive_repetition")
        b = FailureSignature(session_id="s2", task_id="t2", terminal_cause="timeout",
                              agent_behavior="retry_loop", mechanism="unproductive_repetition")
        assert a.cluster_key == b.cluster_key


class TestFailureCluster:
    def test_from_signatures(self):
        from weebot.domain.models.failure_signature import FailureSignature, FailureCluster
        sigs = [
            FailureSignature(session_id="s1", task_id="t1", terminal_cause="timeout",
                              agent_behavior="retry_loop", mechanism="unproductive_repetition"),
            FailureSignature(session_id="s2", task_id="t2", terminal_cause="timeout",
                              agent_behavior="retry_loop", mechanism="unproductive_repetition"),
        ]
        cluster = FailureCluster.from_signatures(sigs)
        assert cluster.support == 2
        assert len(cluster.representative_session_ids) == 2
        assert cluster.mean_actionability >= 0.0

    def test_from_signatures_empty_raises(self):
        from weebot.domain.models.failure_signature import FailureCluster
        with pytest.raises(ValueError, match="empty"):
            FailureCluster.from_signatures([])


class TestEvidenceBundle:
    def test_top_clusters(self):
        from weebot.domain.models.failure_signature import FailureSignature, FailureCluster, EvidenceBundle
        sig = FailureSignature(session_id="s1", task_id="t1", terminal_cause="timeout",
                                agent_behavior="retry_loop", mechanism="unproductive_repetition",
                                actionability_score=0.8)
        clusters = [
            FailureCluster(signature=sig, support=10, representative_session_ids=[], mean_actionability=0.9),
            FailureCluster(signature=sig, support=2, representative_session_ids=[], mean_actionability=0.3),
        ]
        bundle = EvidenceBundle(clusters=clusters, total_failures=12, total_trajectories=100)
        top = bundle.top_clusters(n=1)
        assert len(top) == 1
        assert top[0].support == 10  # highest support × actionability


# ── 2. CQRS Commands ──────────────────────────────────────────────────────

class TestExtractFailureSignatureCommand:
    def test_creation(self):
        from weebot.application.cqrs.commands.failure_signature_commands import (
            ExtractFailureSignatureCommand,
        )
        cmd = ExtractFailureSignatureCommand(
            session_id="s1", task_id="t1", trajectory_text="did X then Y",
            failure_modes=["timeout"], harness_version="0.2.0",
        )
        assert cmd.session_id == "s1"
        assert cmd.trajectory_text == "did X then Y"


class TestClusterFailurePatternsQuery:
    def test_creation(self):
        from weebot.application.cqrs.commands.failure_signature_commands import (
            ClusterFailurePatternsQuery,
        )
        q = ClusterFailurePatternsQuery(min_support=5, lookback_days=14, max_clusters=3)
        assert q.min_support == 5
        assert q.lookback_days == 14


# ── 3. CQRS Handlers ───────────────────────────────────────────────────────

class TestExtractFailureSignatureHandler:
    @pytest.mark.asyncio
    async def test_skip_missing_trace(self):
        from weebot.application.cqrs.handlers.failure_signature_handlers import (
            ExtractFailureSignatureHandler,
        )
        from weebot.application.cqrs.commands.failure_signature_commands import (
            ExtractFailureSignatureCommand,
        )

        llm = AsyncMock()
        repo = AsyncMock()
        handler = ExtractFailureSignatureHandler(llm=llm, trajectory_repo=repo)

        cmd = ExtractFailureSignatureCommand(
            session_id="s1", trajectory_text="",
        )
        result = await handler.handle(cmd)
        assert not result.success
        assert result.error_code == "NO_TRACE"
        repo.save_failure_signature.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_extracts_and_saves(self):
        from weebot.application.cqrs.handlers.failure_signature_handlers import (
            ExtractFailureSignatureHandler,
        )
        from weebot.application.cqrs.commands.failure_signature_commands import (
            ExtractFailureSignatureCommand,
        )

        llm = AsyncMock()
        llm.chat.return_value = MagicMock(
            content='{"terminal_cause": "timeout", "agent_behavior": "retry_loop", "mechanism": "unproductive_repetition"}'
        )
        repo = AsyncMock()
        handler = ExtractFailureSignatureHandler(llm=llm, trajectory_repo=repo)

        cmd = ExtractFailureSignatureCommand(
            session_id="s1", task_id="t1", trajectory_text="agent did X then Y then X again",
            failure_modes=["timeout"],
        )
        result = await handler.handle(cmd)
        assert result.success
        assert result.data["session_id"] == "s1"
        assert result.data["signature"]["terminal_cause"] == "timeout"
        repo.save_failure_signature.assert_awaited_once()


class TestClusterFailurePatternsHandler:
    @pytest.mark.asyncio
    async def test_empty_clusters(self):
        from weebot.application.cqrs.handlers.failure_signature_handlers import (
            ClusterFailurePatternsHandler,
        )
        from weebot.application.cqrs.commands.failure_signature_commands import (
            ClusterFailurePatternsQuery,
        )

        repo = AsyncMock()
        repo.get_clusters.return_value = []
        repo.count_trajectories.return_value = 0

        handler = ClusterFailurePatternsHandler(trajectory_repo=repo)
        query = ClusterFailurePatternsQuery(min_support=3)

        result = await handler.handle(query)
        assert result.success
        assert result.data["total_failures"] == 0


# ── 4. Repository ─────────────────────────────────────────────────────────

class TestTrajectoryRepositoryFailureSignatures:
    """Tests for the failure_signatures table and methods."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test_trajectories.db")

    @pytest.mark.asyncio
    async def test_save_and_cluster(self, db_path):
        """Round-trip: save signature → cluster returns it."""
        from weebot.domain.models.failure_signature import FailureSignature
        from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository

        repo = TrajectoryRepository(db_path=db_path)
        await repo._get_pool()  # initialize schema

        sig = FailureSignature(
            session_id="s1", task_id="t1", terminal_cause="timeout",
            agent_behavior="retry_loop", mechanism="unproductive_repetition",
            actionability_score=0.8, harness_version="0.2.0",
        )
        await repo.save_failure_signature(sig)

        # Add a second with same signature
        sig2 = FailureSignature(
            session_id="s2", task_id="t2", terminal_cause="timeout",
            agent_behavior="retry_loop", mechanism="unproductive_repetition",
            actionability_score=0.7, harness_version="0.2.0",
        )
        await repo.save_failure_signature(sig2)

        clusters = await repo.get_clusters(min_support=2, lookback_days=365, max_clusters=5)
        assert len(clusters) == 1
        assert clusters[0].support == 2
        assert clusters[0].signature.terminal_cause == "timeout"

        await repo.close()

    @pytest.mark.asyncio
    async def test_get_sessions_without_signature(self, db_path):
        from weebot.domain.models.trajectory import TrajectorySummary
        from weebot.domain.models.failure_signature import FailureSignature
        from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository

        repo = TrajectoryRepository(db_path=db_path)
        await repo._get_pool()

        # Add a failed trajectory
        t = TrajectorySummary(
            task_id="t1", session_id="s1", score=0.3, passed=False,
            trajectory_text="agent did X", failure_modes=["timeout"],
        )
        await repo.save(t)

        # Add a passing trajectory
        t2 = TrajectorySummary(
            task_id="t2", session_id="s2", score=0.9, passed=True,
        )
        await repo.save(t2)

        # No signatures exist yet
        missing = await repo.get_sessions_without_signature(lookback_days=365, max_sessions=10)
        assert len(missing) == 1  # only the failed one
        assert missing[0][0] == "s1"

        # Add a signature for s1
        sig = FailureSignature(
            session_id="s1", task_id="t1", terminal_cause="timeout",
            agent_behavior="retry_loop", mechanism="unproductive_repetition",
        )
        await repo.save_failure_signature(sig)

        # Now no sessions should be missing
        missing = await repo.get_sessions_without_signature(lookback_days=365, max_sessions=10)
        assert len(missing) == 0

        await repo.close()
