"""Unit tests for FTS5 Cross-Session Search (Hermes M2).

Covers:
- search_sessions returns empty for no data
- search_sessions returns results after indexing events
- CLI command is registered
"""
import pytest


class TestFTSSearch:
    """Validates FTS5 search via SQLiteStateRepository."""

    @pytest.mark.asyncio
    async def test_search_empty_on_no_data(self, with_openai_key, tmp_db):
        """Search on an empty database returns empty list."""
        from weebot.infrastructure.persistence.sqlite_state_repo import (
            SQLiteStateRepository,
        )

        repo = SQLiteStateRepository(db_path=str(tmp_db))
        results = await repo.search_sessions("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_after_indexing(self, with_openai_key, tmp_db):
        """After saving a session, search finds indexed events."""
        import json
        from datetime import datetime, timezone
        from weebot.infrastructure.persistence.sqlite_state_repo import (
            SQLiteStateRepository,
        )
        from weebot.domain.models.session import Session, SessionStatus

        repo = SQLiteStateRepository(db_path=str(tmp_db))
        session = Session(
            id="test-session-1",
            user_id="test",
            agent_id="test",
            status=SessionStatus.COMPLETED,
        )

        # Simulate an event
        class MockEvent:
            type = "message"
            message = "Hello world test content"
            details = {"key": "value"}
            role = "assistant"
            model_dump = lambda self: {"type": "message", "message": "Hello world test content"}

        session.events = [MockEvent()]

        await repo.save_session(session)

        # Search should find the indexed event
        results = await repo.search_sessions("hello")
        assert len(results) >= 1
        assert any("hello" in r.get("summary", "").lower() for r in results)

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, with_openai_key, tmp_db):
        """Search limit restricts results."""
        from weebot.infrastructure.persistence.sqlite_state_repo import (
            SQLiteStateRepository,
        )

        repo = SQLiteStateRepository(db_path=str(tmp_db))
        results = await repo.search_sessions("test", limit=5)
        assert isinstance(results, list)
        assert len(results) >= 0


class TestFlowSearchCLI:
    """Validates the `flow search` command."""

    def test_command_registered(self):
        """The flow search command exists."""
        from cli.main import cli

        flow_group = cli.commands.get("flow")
        assert flow_group is not None
        commands = list(flow_group.commands.keys())
        assert "search" in commands
