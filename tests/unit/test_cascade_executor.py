"""Unit tests for CascadeExecutor — model cascade, circuit breaker, live rescue.

Tests cover:
- Circuit breaker state machine (tripped/reset/failure recording)
- Single model call with retry
- Parallel probe dispatch
- Sequential fallback
- Live model rescue
- Fast-fail timeout reduction
- AllModelsTrippedError terminal state
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMResponse
from weebot.domain.exceptions import AllModelsTrippedError


@pytest.fixture
def mock_llm():
    """Create a mock LLMPort that returns a simple response."""
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(
        content="Test response",
        tool_calls=None,
        usage=MagicMock(prompt_tokens=10, completion_tokens=20),
    )
    return llm


@pytest.fixture
def mock_tools():
    """Create a mock ToolCollection."""
    tools = MagicMock()
    tools.to_params.return_value = []
    return tools


@pytest.fixture
def executor(mock_llm, mock_tools):
    """Create a CascadeExecutor with mocked dependencies."""
    return CascadeExecutor(
        llm=mock_llm,
        tools=mock_tools,
        agent_role="test_role",
        model_provider=lambda desc: "test/task-model",
        on_success=None,
    )


# ── Circuit breaker tests ─────────────────────────────────────────

class TestCircuitBreaker:
    """Per-model circuit breaker tracking."""

    def test_initial_state_not_tripped(self, executor: CascadeExecutor) -> None:
        assert not executor.cascade_is_tripped("any/model")

    def test_trips_after_5_failures(self, executor: CascadeExecutor) -> None:
        for _ in range(5):
            executor._cascade_record_failure("test/model")
        assert executor.cascade_is_tripped("test/model")

    def test_reset_clears_failures(self, executor: CascadeExecutor) -> None:
        executor._cascade_record_failure("test/model")
        executor._cascade_record_failure("test/model")
        executor._cascade_reset("test/model")
        assert not executor.cascade_is_tripped("test/model")

    def test_tripped_models_return_none(self, executor: CascadeExecutor) -> None:
        for _ in range(5):
            executor._cascade_record_failure("dead/model")
        result = executor.cascade_is_tripped("dead/model")
        assert result is True

    def test_failures_are_per_model(self, executor: CascadeExecutor) -> None:
        executor._cascade_record_failure("model-a")
        executor._cascade_record_failure("model-a")
        executor._cascade_record_failure("model-b")
        assert executor.cascade_is_tripped("model-a") is False  # only 2
        assert executor.cascade_is_tripped("model-b") is False  # only 1

    def test_warning_at_3_failures(self, executor: CascadeExecutor, caplog) -> None:
        import logging
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                executor._cascade_record_failure("warn/model")
        assert "Circuit breaker tripped" in caplog.text


# ── Fast-fail detection ───────────────────────────────────────────

class TestFastFail:
    """Fast-fail on auth/not-found errors."""

    def test_404_is_fast_fail(self, executor: CascadeExecutor) -> None:
        exc = ValueError("404 model not found")
        assert executor._is_fast_fail_error(exc)

    def test_unauthorized_is_fast_fail(self, executor: CascadeExecutor) -> None:
        exc = ValueError("unauthorized: invalid api key")
        assert executor._is_fast_fail_error(exc)

    def test_permission_denied_is_fast_fail(self, executor: CascadeExecutor) -> None:
        exc = ValueError("permission denied")
        assert executor._is_fast_fail_error(exc)

    def test_timeout_is_not_fast_fail(self, executor: CascadeExecutor) -> None:
        import asyncio
        exc = asyncio.TimeoutError("timed out")
        assert not executor._is_fast_fail_error(exc)


# ── Single model call ─────────────────────────────────────────────

class TestSingleModelCall:
    """_cascade_try_chat behavior."""

    @pytest.mark.asyncio
    async def test_successful_call_returns_response(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        resp = await executor._cascade_try_chat(
            [{"role": "user", "content": "hello"}],
            "test/model",
            timeout=10.0,
        )
        assert resp is not None
        assert resp.content == "Test response"
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_tripped_model_returns_none(
        self, executor: CascadeExecutor
    ) -> None:
        for _ in range(5):
            executor._cascade_record_failure("dead/model")
        resp = await executor._cascade_try_chat(
            [{"role": "user", "content": "hello"}],
            "dead/model",
        )
        assert resp is None

    @pytest.mark.asyncio
    async def test_error_records_failure(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        mock_llm.chat.side_effect = ValueError("API error")
        resp = await executor._cascade_try_chat(
            [{"role": "user", "content": "hello"}],
            "failing/model",
        )
        assert resp is None
        assert executor.cascade_is_tripped("failing/model") is False
        # One failure shouldn't trip (need 5)

    @pytest.mark.asyncio
    async def test_fast_fail_raises(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        mock_llm.chat.side_effect = ValueError("unauthorized")
        with pytest.raises(ValueError, match="unauthorized"):
            await executor._cascade_try_chat(
                [{"role": "user", "content": "hello"}],
                "auth/model",
            )


# ── Cascade orchestration ─────────────────────────────────────────

class TestCascadeOrchestration:
    """Full cascade: parallel → sequential → rescue."""

    @pytest.mark.asyncio
    async def test_parallel_probes_first_success_wins(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """First model to respond should be returned."""
        with patch.object(executor, "_model_provider", return_value="fast/model"):
            resp = await executor.call_with_cascade(
                [{"role": "user", "content": "hello"}],
                description="test task",
            )
        assert resp is not None
        assert resp.content == "Test response"

    @pytest.mark.asyncio
    async def test_all_models_fail_raises_error(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """When every model returns None, AllModelsTrippedError is raised."""
        mock_llm.chat.return_value = None  # empty response
        with pytest.raises(AllModelsTrippedError):
            await executor.call_with_cascade(
                [{"role": "user", "content": "hello"}],
                description="failing task",
            )

    @pytest.mark.asyncio
    async def test_on_success_callback_invoked(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """When on_success is set, it should be called after a successful response."""
        callback = AsyncMock()
        executor._on_success = callback
        with patch.object(executor, "_model_provider", return_value="fast/model"):
            resp = await executor.call_with_cascade(
                [{"role": "user", "content": "hello"}],
                description="test task",
            )
        assert resp is not None
        callback.assert_awaited_once()


# ── Live model rescue ─────────────────────────────────────────────

class TestLiveModelRescue:
    """Last-resort fallback to OpenRouter free models."""

    @pytest.mark.asyncio
    async def test_rescue_returns_none_on_network_error(
        self, executor: CascadeExecutor
    ) -> None:
        with patch("httpx.AsyncClient", side_effect=ValueError("network error")):
            result = await executor._live_model_rescue(
                [{"role": "user", "content": "hello"}],
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_rescue_with_no_free_models(
        self, executor: CascadeExecutor
    ) -> None:
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"data": []}
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)
            mock_get.return_value = mock_response
            result = await executor._live_model_rescue(
                [{"role": "user", "content": "hello"}],
            )
        assert result is None
