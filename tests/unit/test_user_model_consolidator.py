"""Tests for UserModelConsolidator."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.user_model_consolidator import UserModelConsolidator
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


class TestUserModelConsolidator:
    @pytest.fixture
    def repo(self):
        # list_behavioral_rules() returns list[dict] in production
        # (sqlite_state_repo.py -> _behavioral_rule_repo.py: [dict(r) for r in rows]).
        # A pydantic BehavioralRule fixture here would hide a `.rule_text`
        # attribute-access bug that is an AttributeError against real data.
        r = MagicMock()
        r.list_behavioral_rules = AsyncMock(
            return_value=[
                {
                    "id": "r1",
                    "rule_text": "Never use rm -rf",
                    "source_session_id": "s1",
                    "source_message": "",
                    "scope": "global",
                    "applied_count": 3,
                }
            ]
        )
        r.get_low_salience_entries = AsyncMock(return_value=[])
        r.upsert_memory_metadata = AsyncMock(spec=SQLiteStateRepository.upsert_memory_metadata)
        return r

    async def test_consolidate_without_llm(self, repo):
        consolidator = UserModelConsolidator(state_repo=repo, llm=None)
        profile = await consolidator.consolidate()
        assert "Never use rm -rf" in profile
        assert "User Profile" in profile

    async def test_consolidate_no_data(self):
        repo = MagicMock()
        repo.list_behavioral_rules = AsyncMock(return_value=[])
        repo.get_low_salience_entries = AsyncMock(return_value=[])
        repo.upsert_memory_metadata = AsyncMock()

        consolidator = UserModelConsolidator(state_repo=repo, llm=None)
        profile = await consolidator.consolidate()
        assert profile == "No user data collected yet."

    async def test_consolidate_with_llm(self, repo):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()
        mock_llm.chat.return_value.content = "User prefers safe commands."

        consolidator = UserModelConsolidator(state_repo=repo, llm=mock_llm)
        profile = await consolidator.consolidate()
        assert mock_llm.chat.called
        assert profile == "User prefers safe commands."
        # Verify profile was stored with correct entry_text
        repo.upsert_memory_metadata.assert_awaited_once()
        _, kwargs = repo.upsert_memory_metadata.call_args
        assert kwargs.get("entry_text") == "User prefers safe commands."
        assert kwargs.get("salience") == 1.0
