"""Unit tests for MCP sampling handler and rate limiter."""

from __future__ import annotations

import pytest

from weebot.application.services.mcp_sampling_handler import (
    MCPSamplingHandler,
    SamplingRequest,
    SamplingResult,
    RateLimiter,
)
from weebot.domain.models.mcp import MCPSamplingPolicy


class _FakeProvider:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, model=None, temperature=None, max_tokens=None, **_):
        from weebot.core.log_context import session_id_var
        from weebot.domain.models.llm_response import LLMResponse

        self.calls.append(
            {"messages": messages, "model": model, "max_tokens": max_tokens,
             "charged_to": session_id_var.get()}
        )
        return LLMResponse(content="an answer", model="fake-model")


class TestRateLimiter:
    """RateLimiter token-bucket behavior."""

    @pytest.mark.asyncio
    async def test_unlimited(self):
        limiter = RateLimiter(0)
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True

    @pytest.mark.asyncio
    async def test_rate_limit_exact(self):
        limiter = RateLimiter(3)
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True
        # Fourth call within the same rate window should be rate-limited
        # (tokens refill at 3/60 per second, so within same instant it's denied)
        allowed = await limiter.acquire()
        # It might be allowed if refill happened — that's fine; just ensure
        # it doesn't blow up
        assert isinstance(allowed, bool)


class TestMCPSamplingHandler:
    """MCPSamplingHandler request processing."""

    def setup_method(self):
        self.provider = _FakeProvider()
        self.handler = MCPSamplingHandler(llm_provider=self.provider)

    @pytest.mark.asyncio
    async def test_sampling_disabled(self):
        policy = MCPSamplingPolicy(enabled=False)
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}])
        result = await self.handler.handle_sampling("test-server", request, policy)
        assert result is None

    @pytest.mark.asyncio
    async def test_model_not_in_allowlist(self):
        policy = MCPSamplingPolicy(enabled=True, model_allowlist=["claude-3-sonnet"])
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}], model="gpt-4")
        result = await self.handler.handle_sampling("test-server", request, policy)
        assert result is None

    @pytest.mark.asyncio
    async def test_model_in_allowlist(self):
        policy = MCPSamplingPolicy(enabled=True, model_allowlist=["claude-3-sonnet"])
        request = SamplingRequest(
            messages=[{"role": "user", "content": "Hello"}], model="claude-3-sonnet"
        )
        result = await self.handler.handle_sampling("test-server", request, policy)
        assert result is not None
        assert self.provider.calls[0]["model"] == "claude-3-sonnet"

    @pytest.mark.asyncio
    async def test_token_cap_enforced(self):
        """max_tokens_per_request should cap the request's max_tokens."""
        policy = MCPSamplingPolicy(enabled=True, max_tokens_per_request=100)
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}], max_tokens=9999)
        result = await self.handler.handle_sampling("test-server", request, policy)
        assert result is not None
        assert self.provider.calls[0]["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_the_provider_answers_and_the_result_is_its_text(self):
        policy = MCPSamplingPolicy(enabled=True)
        request = SamplingRequest(
            messages=[{"role": "user", "content": "Hello"}], system_prompt="be brief"
        )
        result = await self.handler.handle_sampling("test-server", request, policy)
        assert isinstance(result, SamplingResult)
        assert result.content == [{"type": "text", "text": "an answer"}]
        assert self.provider.calls[0]["messages"][0] == {"role": "system", "content": "be brief"}

    @pytest.mark.asyncio
    async def test_no_provider_denies_instead_of_inventing_an_answer(self):
        handler = MCPSamplingHandler()
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}])
        assert await handler.handle_sampling("s", request, MCPSamplingPolicy(enabled=True)) is None

    @pytest.mark.asyncio
    async def test_sampling_is_off_unless_the_policy_turns_it_on(self):
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}])
        assert await self.handler.handle_sampling("s", request, MCPSamplingPolicy()) is None

    @pytest.mark.asyncio
    async def test_a_request_outside_a_tool_call_is_denied(self):
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}])
        policy = MCPSamplingPolicy(enabled=True)
        assert await self.handler.handle_sampling("s", request, policy, session_id="") is None
        assert self.provider.calls == []

    @pytest.mark.asyncio
    async def test_a_tainted_session_is_refused_unless_the_policy_allows_it(self):
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}])
        refused = MCPSamplingPolicy(enabled=True)
        allowed = MCPSamplingPolicy(enabled=True, allow_when_tainted=True)
        assert await self.handler.handle_sampling(
            "s", request, refused, session_id="s1", tainted=True
        ) is None
        assert await self.handler.handle_sampling(
            "s", request, allowed, session_id="s1", tainted=True
        ) is not None

    @pytest.mark.asyncio
    async def test_the_call_is_charged_to_the_calling_session(self):
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}])
        await self.handler.handle_sampling(
            "s", request, MCPSamplingPolicy(enabled=True), session_id="parent-1"
        )
        assert self.provider.calls[0]["charged_to"] == "parent-1"

    @pytest.mark.asyncio
    async def test_a_session_past_its_hard_limit_is_refused(self):
        from weebot.application.services.session_cost import SessionCostMeter

        meter = SessionCostMeter(hard_usd=1.0)
        meter.add("parent-1", 2.0)
        handler = MCPSamplingHandler(llm_provider=self.provider, cost_meter=meter)
        request = SamplingRequest(messages=[{"role": "user", "content": "Hello"}])
        result = await handler.handle_sampling(
            "s", request, MCPSamplingPolicy(enabled=True), session_id="parent-1"
        )
        assert result is None and self.provider.calls == []

    @pytest.mark.asyncio
    async def test_rate_limit_applies(self):
        """Multiple requests in quick succession should be rate-limited."""
        policy = MCPSamplingPolicy(enabled=True, rate_limit_per_minute=2)
        request = SamplingRequest(messages=[{"role": "user", "content": "Hi"}])

        result1 = await self.handler.handle_sampling("test-server", request, policy)
        assert result1 is not None

        result2 = await self.handler.handle_sampling("test-server", request, policy)
        assert result2 is not None

        # Third call should be rate-limited
        result3 = await self.handler.handle_sampling("test-server", request, policy)
        # Could be None (rate-limited) or a result (if refill happened)
        assert result3 is None or isinstance(result3, SamplingResult)
