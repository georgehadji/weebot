"""Tests for UserModelConsolidator."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.user_model_consolidator import UserModelConsolidator
from weebot.domain.models.behavioral_rule import BehavioralRule


class TestUserModelConsolidator:
    @pytest.fixture
    def repo(self):
        r = MagicMock()
        r.list_behavioral_rules = AsyncMock(return_value=[
            BehavioralRule(
                id="r1", rule_text="Never use rm -rf",
                source_session_id="s1", source_message="",
                scope="global", applied_count=3,
            ),
        ])
        r.get_low_salience_entries = AsyncMock(return_value=[])
        r.upsert_memory_metadata = AsyncMock()
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
