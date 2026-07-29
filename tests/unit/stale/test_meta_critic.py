"""Tests for MetaCritic — post-task trajectory analysis."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.meta_critic import (
    MetaCritic,
    MetaCritiqueResult,
    _META_CRITIC_SYSTEM_PROMPT,
)


class TestMetaCritiqueResult:
    """Tests for the MetaCritiqueResult dataclass."""

    def test_empty_result_has_no_insights(self) -> None:
        result = MetaCritiqueResult.empty()
        assert result.meta_note == "No actionable insights"
        assert result.what_worked == []
        assert result.what_failed == []
        assert result.strategy_change == ""

    def test_meta_note_includes_strategy_change(self) -> None:
        result = MetaCritiqueResult(
            what_worked=["Good tool choice"],
            what_failed=["Browser timeout"],
            strategy_change="Use web_search instead of advanced_browser for read-only pages",
        )
        note = result.meta_note
        assert "Use web_search" in note
        assert "Browser timeout" in note

    def test_meta_note_without_strategy_still_shows_failures(self) -> None:
        result = MetaCritiqueResult(
            what_worked=[],
            what_failed=["Step 3 repeated 5 times"],
            strategy_change="",
        )
        assert "Step 3 repeated 5 times" in result.meta_note


class TestMetaCriticParse:
    """Tests for JSON response parsing."""

    def test_parse_valid_json(self) -> None:
        raw = json.dumps({
            "what_worked": ["Good planning"],
            "what_failed": ["Timeout on goto"],
            "strategy_change": "Use domcontentloaded",
        })
        result = MetaCritic._parse_response(raw)
        assert result is not None
        assert result.what_worked == ["Good planning"]
        assert result.strategy_change == "Use domcontentloaded"

    def test_parse_json_with_code_fences(self) -> None:
        raw = '```json\n{"what_worked":[],"what_failed":[],"strategy_change":"test"}\n```'
        result = MetaCritic._parse_response(raw)
        assert result is not None
        assert result.strategy_change == "test"

    def test_parse_invalid_json_returns_none(self) -> None:
        result = MetaCritic._parse_response("not json at all")
        assert result is None

    def test_parse_empty_string_returns_none(self) -> None:
        result = MetaCritic._parse_response("")
        assert result is None

    def test_parse_missing_fields_uses_defaults(self) -> None:
        result = MetaCritic._parse_response('{"what_worked":["x"]}')
        assert result is not None
        assert result.what_worked == ["x"]
        assert result.what_failed == []
        assert result.strategy_change == ""


class TestMetaCriticCritique:
    """Tests for the critique method with mocked LLM."""

    @pytest.fixture
    def mock_llm(self) -> AsyncMock:
        llm = AsyncMock()
        llm.chat = AsyncMock()
        return llm

    @pytest.fixture
    def critic(self, mock_llm: AsyncMock) -> MetaCritic:
        return MetaCritic(llm=mock_llm)

    @pytest.mark.asyncio
    async def test_critique_returns_result(self, critic: MetaCritic, mock_llm: AsyncMock) -> None:
        mock_llm.chat.return_value = MagicMock(
            content=json.dumps({
                "what_worked": ["Fast execution"],
                "what_failed": ["Wrong tool"],
                "strategy_change": "Use bash instead of browser",
            })
        )

        result = await critic.critique(
            task_description="Test task",
            plan_summary="Test plan",
            step_results=[("step-1", "Done")],
            failures=[],
            tool_count=3,
        )

        assert result.what_worked == ["Fast execution"]
        assert result.strategy_change == "Use bash instead of browser"

    @pytest.mark.asyncio
    async def test_critique_handles_llm_failure(self, critic: MetaCritic, mock_llm: AsyncMock) -> None:
        mock_llm.chat.side_effect = RuntimeError("LLM unavailable")

        result = await critic.critique(
            task_description="Test",
            plan_summary="Plan",
            step_results=[],
            failures=[],
        )

        assert result == MetaCritiqueResult.empty()

    @pytest.mark.asyncio
    async def test_critique_truncates_long_step_results(self, critic: MetaCritic, mock_llm: AsyncMock) -> None:
        mock_llm.chat.return_value = MagicMock(
            content=json.dumps({
                "what_worked": [],
                "what_failed": [],
                "strategy_change": "",
            })
        )

        long_result = "x" * 500
        await critic.critique(
            task_description="Test",
            plan_summary="Plan",
            step_results=[("step-1", long_result)],
            failures=[],
        )

        # Verify the prompt only contains truncated result
        call_args = mock_llm.chat.call_args
        messages = call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        assert "x" * 200 in user_content
        assert "x" * 500 not in user_content  # was truncated


class TestSystemPrompt:
    """Verify the system prompt contains required output fields."""

    def test_prompt_requests_what_worked(self) -> None:
        assert "what_worked" in _META_CRITIC_SYSTEM_PROMPT

    def test_prompt_requests_what_failed(self) -> None:
        assert "what_failed" in _META_CRITIC_SYSTEM_PROMPT

    def test_prompt_requests_strategy_change(self) -> None:
        assert "strategy_change" in _META_CRITIC_SYSTEM_PROMPT
