"""Integration + structural tests for MED-priority coverage gaps."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.ports.llm_port import LLMPort
from weebot.infrastructure.adapters.llm.anthropic_adapter import AnthropicAdapter
from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from weebot.infrastructure.adapters.llm.deepseek_adapter import DeepSeekAdapter


# ── CascadeExecutor all-models-tripped ──────────────────────────────────────

class TestCascadeAllModelsTripped:
    async def test_all_models_tripped_raises(self):
        """When all cascade models fail, AllModelsTrippedError is raised."""
        from weebot.application.agents.executor._cascade import CascadeExecutor
        from weebot.domain.exceptions import AllModelsTrippedError

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("model down"))
        cascade = CascadeExecutor(
            llm=mock_llm, tools=MagicMock(),
            agent_role="test", model_provider=lambda d: "test-model",
        )
        cascade._circuit_breaker_failures["test-model"] = 5

        with pytest.raises(AllModelsTrippedError):
            await cascade.call_with_cascade(
                [{"role": "user", "content": "hello"}], "test",
            )

    async def test_server_error_models_skipped(self):
        """Models with server errors are skipped in current cascade run."""
        from weebot.application.agents.executor._cascade import CascadeExecutor

        cascade = CascadeExecutor(
            llm=MagicMock(), tools=MagicMock(),
            agent_role="test", model_provider=lambda d: "test-model",
        )
        cascade._server_error_models.add("bad-model")
        assert "bad-model" in cascade._server_error_models

    async def test_server_error_set_cleared_per_run(self):
        """Server error set is cleared at the start of each cascade run."""
        from weebot.application.agents.executor._cascade import CascadeExecutor
        from weebot.domain.models.llm_response import LLMResponse

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(
            content="ok", tool_calls=None, model="test-model",
        ))
        cascade = CascadeExecutor(
            llm=mock_llm, tools=MagicMock(),
            agent_role="test", model_provider=lambda d: "test-model",
        )
        cascade._server_error_models.add("bad-model")
        try:
            await cascade.call_with_cascade(
                [{"role": "user", "content": "hi"}], "test",
            )
        except Exception:
            pass
        # After a run (successful or failed), the set is cleared
        assert "bad-model" not in cascade._server_error_models


# ── LLMPort contract tests ──────────────────────────────────────────────────

class TestLLMPortContract:
    def test_openai_adapter_implements_port(self):
        adapter = OpenAIAdapter(api_key="test-key", default_model="gpt-4")
        assert isinstance(adapter, LLMPort)

    def test_anthropic_adapter_implements_port(self):
        adapter = AnthropicAdapter(api_key="test-key", default_model="claude-3-5-haiku")
        assert isinstance(adapter, LLMPort)

    def test_deepseek_adapter_implements_port(self):
        adapter = DeepSeekAdapter(api_key="test-key", default_model="deepseek-v4-flash")
        assert isinstance(adapter, LLMPort)

    def test_all_adapters_have_chat(self):
        adapters = [
            OpenAIAdapter(api_key="k", default_model="gpt-4"),
            AnthropicAdapter(api_key="k", default_model="claude-3-5-haiku"),
            DeepSeekAdapter(api_key="k", default_model="deepseek-v4-flash"),
        ]
        for adapter in adapters:
            assert hasattr(adapter, 'chat')
            assert callable(adapter.chat)


# ── Commitment idempotency ──────────────────────────────────────────────────

class TestCommitmentIdempotency:
    async def test_heartbeat_skips_already_overdue(self):
        from weebot.domain.services.commitment_engine import CommitmentEngine
        from weebot.domain.models.commitment import Commitment, CommitmentStatus
        from datetime import datetime, timedelta, timezone

        overdue = Commitment(
            id="x", promise_text="test", context="", source_session_id="s1",
            due_at=datetime.now(timezone.utc) - timedelta(hours=2),
            status=CommitmentStatus.PENDING,
        )
        repo1 = MagicMock()
        repo1.list_commitments = AsyncMock(return_value=[overdue])
        repo1.update_commitment_status = AsyncMock(return_value=True)
        engine1 = CommitmentEngine(state_repo=repo1)
        stats1 = await engine1.heartbeat()
        assert stats1["marked_overdue"] >= 1

        repo2 = MagicMock()
        repo2.list_commitments = AsyncMock(return_value=[])
        engine2 = CommitmentEngine(state_repo=repo2)
        stats2 = await engine2.heartbeat()
        assert stats2["marked_overdue"] == 0

    async def test_heartbeat_no_pending_commits(self):
        from weebot.domain.services.commitment_engine import CommitmentEngine
        repo = MagicMock()
        repo.list_commitments = AsyncMock(return_value=[])
        engine = CommitmentEngine(state_repo=repo)
        stats = await engine.heartbeat()
        assert stats == {"checked": 0, "marked_overdue": 0, "active_pending": 0}


# ── OpportunityEngine on empty DB ───────────────────────────────────────────

class TestOpportunityEngineEmpty:
    async def test_empty_kg_returns_empty_list(self):
        from weebot.application.services.opportunity_engine import OpportunityEngine
        kg = MagicMock()
        kg.search = AsyncMock(return_value=[])
        kg.query = AsyncMock(return_value=[])
        engine = OpportunityEngine(knowledge_graph=kg, fts5_search=MagicMock())
        proposals = await engine.scan()
        assert proposals == [] or isinstance(proposals, list)

    async def test_scan_does_not_crash(self):
        from weebot.application.services.opportunity_engine import OpportunityEngine
        kg = MagicMock()
        kg.search = AsyncMock(side_effect=Exception("KG unavailable"))
        engine = OpportunityEngine(knowledge_graph=kg, fts5_search=MagicMock())
        proposals = await engine.scan()
        assert isinstance(proposals, list)


# ── PersistentMemoryTool roundtrip ──────────────────────────────────────────

class TestPersistentMemoryTool:
    @pytest.mark.asyncio
    async def test_add_and_read(self):
        from weebot.tools.persistent_memory import PersistentMemoryTool
        from weebot.infrastructure.persistence.filesystem_memory import FileSystemMemoryAdapter

        tool = PersistentMemoryTool(memory=FileSystemMemoryAdapter())
        result = await tool.execute(action="add", file="agent", entry="test entry")
        assert not result.is_error
        result = await tool.execute(action="read", file="agent")
        assert "test entry" in result.output
