"""Tests for CommitmentExtractor and CommitmentEngine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from weebot.application.services.commitment_extractor import extract_commitments
from weebot.application.services.commitment_engine import CommitmentEngine
from weebot.domain.models.commitment import Commitment, CommitmentStatus


# ── CommitmentExtractor ──────────────────────────────────────────────────────

class TestExtractCommitments:
    def test_extract_follow_up(self):
        text = "I'll check back in 2 hours to see if the build finished."
        results = extract_commitments(text)
        assert len(results) == 1
        assert "check back" in results[0].promise_text
        assert results[0].due_at is not None

    def test_extract_monitor(self):
        text = "Let me keep an eye on that for you."
        results = extract_commitments(text)
        assert len(results) == 1
        assert "keep an eye" in results[0].promise_text

    def test_extract_notify(self):
        text = "I'll let you know when the results come in."
        results = extract_commitments(text)
        assert len(results) == 1
        assert "let you know" in results[0].promise_text

    def test_extract_investigate(self):
        text = "Let me look into why that error occurred."
        results = extract_commitments(text)
        assert len(results) == 1
        assert "look into" in results[0].promise_text

    def test_multiple_commitments(self):
        text = "I'll check back in 1 hour. Also, let me monitor that for you."
        results = extract_commitments(text)
        assert len(results) == 2

    def test_no_commitments(self):
        text = "The answer is 42."
        results = extract_commitments(text)
        assert len(results) == 0

    def test_empty_text(self):
        assert extract_commitments("") == []
        assert extract_commitments("  ") == []

    def test_due_at_parsed(self):
        text = "I'll follow up in 3 days."
        results = extract_commitments(text)
        assert len(results) == 1
        assert results[0].due_at is not None
        # Should be ~3 days from now
        diff = results[0].due_at - datetime.now(timezone.utc)
        assert timedelta(days=2.5) < diff < timedelta(days=3.5)

    def test_due_at_tomorrow(self):
        text = "I'll check back tomorrow."
        results = extract_commitments(text)
        assert len(results) == 1
        assert results[0].due_at is not None
        diff = results[0].due_at - datetime.now(timezone.utc)
        assert timedelta(hours=23) < diff < timedelta(hours=25)

    def test_context_passed_through(self):
        text = "I'll get back to you."
        results = extract_commitments(text, context="User asked about project status")
        assert len(results) == 1
        assert "User asked" in results[0].context

    def test_session_id_stored(self):
        text = "Let me check on that."
        results = extract_commitments(text, source_session_id="sess_123")
        assert results[0].source_session_id == "sess_123"

    def test_status_is_pending(self):
        text = "I'll investigate that."
        results = extract_commitments(text)
        assert results[0].status == CommitmentStatus.PENDING

    def test_circle_back_detected(self):
        text = "I'll circle back once I have the data."
        results = extract_commitments(text)
        assert len(results) == 1


# ── CommitmentEngine ─────────────────────────────────────────────────────────

class TestCommitmentEngineHeartbeat:
    @pytest.fixture
    def engine(self):
        repo = MagicMock()
        return CommitmentEngine(state_repo=repo)

    async def test_heartbeat_marks_overdue(self, engine):
        """Commitments past their due_at are marked overdue."""
        overdue = Commitment(
            id="cmt-1",
            promise_text="check back",
            context="",
            source_session_id="s-1",
            due_at=datetime.now(timezone.utc) - timedelta(hours=1),
            status=CommitmentStatus.PENDING,
        )
        engine._repo.list_commitments = AsyncMock(return_value=[overdue])
        engine._repo.update_commitment_status = AsyncMock(return_value=True)

        stats = await engine.heartbeat()
        assert stats["marked_overdue"] == 1
        engine._repo.update_commitment_status.assert_called_once_with(
            "cmt-1", "overdue", failure_reason=ANY,
        )

    async def test_heartbeat_no_overdue(self, engine):
        """Commitments within their due_at are not marked."""
        pending = Commitment(
            id="cmt-2",
            promise_text="monitor",
            context="",
            source_session_id="s-1",
            due_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status=CommitmentStatus.PENDING,
        )
        engine._repo.list_commitments = AsyncMock(return_value=[pending])
        engine._repo.update_commitment_status = AsyncMock()

        stats = await engine.heartbeat()
        assert stats["marked_overdue"] == 0
        engine._repo.update_commitment_status.assert_not_called()

    async def test_heartbeat_handles_repo_error(self, engine):
        """If the repo fails, heartbeat returns zeros gracefully."""
        engine._repo.list_commitments = AsyncMock(side_effect=Exception("DB error"))
        stats = await engine.heartbeat()
        assert stats == {"checked": 0, "marked_overdue": 0, "active_pending": 0}


class TestCommitmentEngineSurfacing:
    @pytest.fixture
    def engine(self):
        repo = MagicMock()
        return CommitmentEngine(state_repo=repo)

    async def test_summary_with_overdue(self, engine):
        overdue = Commitment(
            id="cmt-1", promise_text="check back in 2 hours",
            context="user asked for status", source_session_id="s-1",
            due_at=datetime.now(timezone.utc) - timedelta(hours=1),
            status=CommitmentStatus.OVERDUE,
        )
        engine._repo.get_pending_commitments = AsyncMock(return_value=[overdue])
        summary = await engine.get_pending_summary()
        assert "overdue" in summary.lower()
        assert "check back" in summary

    async def test_summary_with_pending(self, engine):
        pending = Commitment(
            id="cmt-2", promise_text="monitor the deployment",
            context="", source_session_id="s-1",
            due_at=datetime.now(timezone.utc) + timedelta(hours=2),
            status=CommitmentStatus.PENDING,
        )
        engine._repo.get_pending_commitments = AsyncMock(return_value=[pending])
        summary = await engine.get_pending_summary()
        assert "pending" in summary.lower()
        assert "monitor" in summary

    async def test_summary_empty_when_none(self, engine):
        engine._repo.get_pending_commitments = AsyncMock(return_value=[])
        summary = await engine.get_pending_summary()
        assert summary == ""

    async def test_summary_handles_repo_error(self, engine):
        engine._repo.get_pending_commitments = AsyncMock(side_effect=Exception("DB error"))
        summary = await engine.get_pending_summary()
        assert summary == ""
