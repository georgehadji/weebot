"""Tests for SessionSearchService."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.services.session_search_service import SessionSearchService


class TestSessionSearchService:
    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.id = "sess-123"
        session.title = "Test task"
        session.events = []
        return session

    async def test_search_returns_enriched_results(self, mock_session):
        """search() returns SearchResult objects with goal and resolution."""
        repo = MagicMock()
        repo.search_sessions = AsyncMock(return_value=[
            {"session_id": "sess-123", "summary": "error occurred", "score": 0.9},
        ])
        repo.load_session = AsyncMock(return_value=mock_session)

        svc = SessionSearchService(state_repo=repo)
        results = await svc.search("error", limit=5)

        assert len(results) == 1
        assert results[0].session_id == "sess-123"
        assert results[0].goal == "Test task"
        assert results[0].score == 0.9

    async def test_search_empty_results(self):
        """Empty search results return empty list."""
        repo = MagicMock()
        repo.search_sessions = AsyncMock(return_value=[])
        svc = SessionSearchService(state_repo=repo)
        results = await svc.search("nothing", limit=5)
        assert results == []
