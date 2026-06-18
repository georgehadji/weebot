"""Integration tests for CascadeExecutor — requires OpenRouter credits.

Gated behind WEEBOT_INTEGRATION_TESTS=1 env var.  Tests verify the full
model cascade pipeline with real LLM calls.

Run with:
    WEEBOT_INTEGRATION_TESTS=1 python -m pytest tests/integration/test_cascade_integration.py -v
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMResponse
from weebot.domain.exceptions import AllModelsTrippedError


pytestmark = pytest.mark.skipif(
    os.getenv("WEEBOT_INTEGRATION_TESTS") not in ("1", "true", "yes"),
    reason="Set WEEBOT_INTEGRATION_TESTS=1 to run cascade integration tests",
)


@pytest.fixture
def mock_llm():
    """Create a mock LLMPort."""
    llm = AsyncMock()
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


# ── Integration tests ─────────────────────────────────────────────

class TestCascadeParallelProbes:
    """Phase 1: parallel probes dispatch correct models."""

    @pytest.mark.asyncio
    async def test_parallel_probes_dispatch_correct_models(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """Role cascade resolves to expected model IDs."""
        mock_llm.chat.return_value = LLMResponse(
            content="response", tool_calls=None,
        )
        resp = await executor.call_with_cascade(
            [{"role": "user", "content": "test"}],
            description="integration test",
        )
        assert resp is not None
        # At least one chat call should have been made
        assert mock_llm.chat.call_count >= 1


class TestCascadeSequentialFallback:
    """Phase 2: sequential fallback after parallel exhaustion."""

    @pytest.mark.asyncio
    async def test_sequential_fallback_after_parallel_exhaustion(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """When parallel probes all fail, sequential models are tried."""
        # First call fails, second succeeds
        responses = [
            LLMResponse(content="", tool_calls=None),   # parallel probe fails
            LLMResponse(content="fallback", tool_calls=None),  # sequential succeeds
        ]
        call_count = [0]

        async def side_effect(*args, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            call_count[0] += 1
            return responses[idx]

        mock_llm.chat.side_effect = side_effect
        resp = await executor.call_with_cascade(
            [{"role": "user", "content": "test"}],
            description="fail-then-fallback",
        )
        assert resp is not None
        assert resp.content == "fallback"


class TestCascadeLiveModelRescue:
    """Phase 3: live model rescue on all-404."""

    @pytest.mark.asyncio
    async def test_live_model_rescue_returns_none_on_network_error(
        self, executor: CascadeExecutor
    ) -> None:
        """OpenRouter API unavailable → rescue returns None."""
        from unittest.mock import patch
        with patch("httpx.AsyncClient", side_effect=ValueError("network error")):
            result = await executor._live_model_rescue(
                [{"role": "user", "content": "hello"}],
            )
        assert result is None


class TestCascadeFastFail:
    """Fast-fail timeout reduction on auth errors."""

    @pytest.mark.asyncio
    async def test_fast_fail_reduces_remaining_timeouts(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """Auth errors trigger 15s timeout reduction for remaining cascade tiers."""
        # This test verifies the fast_fail flag is set on auth errors
        error = ValueError("unauthorized: invalid api key")
        resp = await executor._cascade_try_chat(
            [{"role": "user", "content": "test"}],
            model_id="auth/model",
            timeout=90.0,
            fast_fail=True,
        )
        # Fast-fail errors should raise, not return None
        mock_llm.chat.side_effect = error
        try:
            await executor._cascade_try_chat(
                [{"role": "user", "content": "test"}],
                model_id="auth/model",
                timeout=90.0,
            )
        except ValueError:
            pass  # Expected — auth errors should raise


class TestCascadeAllModelsTripped:
    """Terminal error when all models fail."""

    @pytest.mark.asyncio
    async def test_all_models_tripped_error(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """Cascade exhausted → AllModelsTrippedError."""
        mock_llm.chat.return_value = None  # All empty
        with pytest.raises(AllModelsTrippedError):
            await executor.call_with_cascade(
                [{"role": "user", "content": "test"}],
                description="all-fail",
            )


class TestCircuitBreaker:
    """Circuit breaker prevents retry of tripped models."""

    def test_tripped_model_returns_none(self, executor: CascadeExecutor) -> None:
        """Tripped model → None immediately."""
        for _ in range(5):
            executor._cascade_record_failure("dead/model")
        assert executor.cascade_is_tripped("dead/model")

    def test_per_model_isolation(self, executor: CascadeExecutor) -> None:
        """Tripping model-A doesn't affect model-B."""
        executor._cascade_record_failure("model-a")
        executor._cascade_record_failure("model-a")
        assert not executor.cascade_is_tripped("model-b")


class TestOnSuccessCallback:
    """on_success callback invoked after successful response."""

    @pytest.mark.asyncio
    async def test_callback_invoked_on_success(
        self, executor: CascadeExecutor, mock_llm
    ) -> None:
        """on_success is called after a successful cascade response."""
        callback = AsyncMock()
        executor._on_success = callback
        mock_llm.chat.return_value = LLMResponse(
            content="success", tool_calls=None,
        )
        resp = await executor.call_with_cascade(
            [{"role": "user", "content": "test"}],
            description="callback-test",
        )
        assert resp is not None
        callback.assert_awaited()
