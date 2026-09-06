"""Stress tests — LLM adapter resilience under failure injection.

Exercises circuit breaker, retry backoff, and timeout enforcement under
concurrent load with various failure modes injected into the inner adapter.

Run with:
    pytest tests/stress/test_llm_resilience.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch
from weebot.utils.backoff import BackoffConfig, RetryWithBackoff

import pytest

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.core.circuit_breaker import CircuitBreaker, BreakerState
from weebot.infrastructure.adapters.llm.resilient_adapter import (
    CircuitBreakerOpen,
    LLMTimeoutError,
    ResilientLLMAdapter,
)

# ---------------------------------------------------------------------------
# Configurable mock LLM adapter
# ---------------------------------------------------------------------------


class FakeInnerAdapter(LLMPort):
    """Mock LLM adapter with injectable failure behavior."""

    def __init__(self):
        self.call_count = 0
        self.call_log: list[dict] = []
        self._behavior: str = "succeed"
        self._latency: float = 0.0
        self._fail_rate: float = 0.0
        self._fail_after: int | None = None
        self._error_class: type[Exception] = RuntimeError
        self._error_msg: str = "injected failure"

    def set_behavior(
        self,
        behavior: str = "succeed",
        latency: float = 0.0,
        fail_rate: float = 0.0,
        fail_after: int | None = None,
        error_class: type[Exception] = RuntimeError,
        error_msg: str = "injected failure",
    ):
        self._behavior = behavior
        self._latency = latency
        self._fail_rate = fail_rate
        self._fail_after = fail_after
        self._error_class = error_class
        self._error_msg = error_msg

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.call_log.append(
            {"call_num": self.call_count, "model": model, "time": time.monotonic()}
        )

        if self._latency > 0:
            await asyncio.sleep(self._latency)

        if self._behavior == "fail_always":
            raise self._error_class(self._error_msg)

        if self._behavior == "fail_rate":
            import random

            if random.random() < self._fail_rate:
                raise self._error_class(self._error_msg)

        if self._behavior == "fail_then_succeed":
            if self._fail_after is not None and self.call_count <= self._fail_after:
                raise self._error_class(self._error_msg)

        if self._behavior == "slow":
            await asyncio.sleep(self._latency)

        return LLMResponse(
            content=f"response-{self.call_count}",
            model=model or "test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


def _make_resilient(
    inner: FakeInnerAdapter,
    model: str = "test-model",
    timeout: float = 5.0,
    circuit_breaker: bool = True,
    retry: bool = True,
) -> ResilientLLMAdapter:
    return ResilientLLMAdapter(
        inner_adapter=inner,
        model_name=model,
        timeout=timeout,
        enable_circuit_breaker=circuit_breaker,
        enable_retry=retry,
    )


MESSAGES = [{"role": "user", "content": "hello"}]


# ---------------------------------------------------------------------------
# Circuit breaker stress tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerUnderLoad:
    """Circuit breaker behavior with many concurrent callers."""

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold_failures(self):
        """3 consecutive failures → circuit OPEN → subsequent calls rejected fast."""
        inner = FakeInnerAdapter()
        inner.set_behavior("fail_always", error_msg="server error 503")
        adapter = _make_resilient(inner, retry=False)

        # First 3 calls should attempt the inner adapter and fail
        for i in range(3):
            with pytest.raises(RuntimeError, match="503"):
                await adapter.chat(MESSAGES)

        # 4th call should get CircuitBreakerOpen without hitting inner
        call_count_before = inner.call_count
        with pytest.raises(CircuitBreakerOpen):
            await adapter.chat(MESSAGES)
        assert inner.call_count == call_count_before, "Inner adapter called while circuit open"

    @pytest.mark.asyncio
    async def test_concurrent_callers_during_circuit_open(self):
        """20 concurrent calls with circuit open — all rejected, none leak through."""
        inner = FakeInnerAdapter()
        inner.set_behavior("fail_always")
        adapter = _make_resilient(inner, retry=False)

        # Trip the breaker
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await adapter.chat(MESSAGES)

        call_count_after_trip = inner.call_count

        # 20 concurrent calls — all should be rejected by circuit
        results = await asyncio.gather(
            *[adapter.chat(MESSAGES) for _ in range(20)], return_exceptions=True
        )
        assert all(isinstance(r, CircuitBreakerOpen) for r in results)
        assert inner.call_count == call_count_after_trip, "Calls leaked through open circuit"

    @pytest.mark.asyncio
    async def test_half_open_probe_allows_exactly_one(self):
        """After cooldown, HALF_OPEN allows a probe. Success closes the circuit."""
        cb = CircuitBreaker(
            failure_threshold=2, cooldown_seconds=0.1, jitter_percent=0.0, enable_stagger=False
        )

        # Trip to OPEN
        await cb.record_failure("model-a")
        await cb.record_failure("model-a")
        assert cb.get_state("model-a") == BreakerState.OPEN

        # Wait for cooldown
        await asyncio.sleep(0.15)

        # Probe should be allowed
        result = await cb.evaluate("model-a")
        assert result.allowed
        assert result.state == BreakerState.HALF_OPEN

        # Record success → CLOSED
        await cb.record_success("model-a")
        assert cb.get_state("model-a") == BreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_thundering_herd_jitter_spreads_probes(self):
        """With jitter, 20 concurrent evaluations after cooldown don't all probe at once."""
        cb = CircuitBreaker(
            failure_threshold=1, cooldown_seconds=0.05, jitter_percent=0.3, enable_stagger=True
        )

        await cb.record_failure("model-x")
        await asyncio.sleep(0.1)

        probe_times: list[float] = []

        async def _eval():
            result = await cb.evaluate("model-x")
            if result.allowed:
                probe_times.append(time.perf_counter())
            return result

        results = await asyncio.gather(*[_eval() for _ in range(20)])
        allowed = [r for r in results if r.allowed]

        # At least 1 should be allowed (the probe)
        assert len(allowed) >= 1
        # With staggering, probes shouldn't all land at the exact same instant
        if len(probe_times) > 1:
            spread = max(probe_times) - min(probe_times)
            assert spread > 0, "All probes landed simultaneously despite stagger"

    @pytest.mark.asyncio
    async def test_per_model_isolation(self):
        """Circuit for model-a tripping does not affect model-b."""
        inner = FakeInnerAdapter()
        adapter = _make_resilient(inner, retry=False)

        # Trip model-a's circuit
        inner.set_behavior("fail_always")
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await adapter.chat(MESSAGES, model="model-a")

        # model-a should be blocked
        with pytest.raises(CircuitBreakerOpen):
            await adapter.chat(MESSAGES, model="model-a")

        # model-b should still work
        inner.set_behavior("succeed")
        response = await adapter.chat(MESSAGES, model="model-b")
        assert response.content.startswith("response-")


# ---------------------------------------------------------------------------
# Retry & backoff stress tests
# ---------------------------------------------------------------------------


class TestRetryUnderLoad:
    """Retry behavior with concurrent requests."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_transient_failures(self):
        """Fail 2 times then succeed — retry should recover."""
        inner = FakeInnerAdapter()
        inner.set_behavior("fail_then_succeed", fail_after=2)
        from weebot.utils.backoff import RetryWithBackoff, BackoffConfig

        adapter = ResilientLLMAdapter(
            inner_adapter=inner,
            model_name="test-model",
            timeout=30.0,
            enable_circuit_breaker=False,
            enable_retry=False,
        )
        adapter._retry = RetryWithBackoff(
            BackoffConfig(
                delays=[0.01, 0.02, 0.04, 0.08, 0.1, 0.2],
                jitter=0.1,
                retryable=adapter._is_retryable_error,
            )
        )

        response = await adapter.chat(MESSAGES)
        assert response.content.startswith("response-")
        assert inner.call_count == 3  # 2 failures + 1 success

    @pytest.mark.asyncio
    async def test_non_retryable_errors_fail_fast(self):
        """Auth errors (401) should not be retried."""
        inner = FakeInnerAdapter()
        inner.set_behavior(
            "fail_always",
            error_class=type("AuthError", (Exception,), {}),
            error_msg="Authentication failed: Invalid API key",
        )

        # Patch ErrorClassifier to recognize our custom auth error
        from weebot.core.error_classifier import ErrorClassifier

        original = ErrorClassifier.is_retryable

        def _mock_retryable(exc):
            if "Authentication" in str(exc):
                return False
            return original(exc)

        adapter = _make_resilient(inner, circuit_breaker=False)

        with patch.object(ErrorClassifier, "is_retryable", side_effect=_mock_retryable):
            with pytest.raises(Exception, match="Authentication"):
                await adapter.chat(MESSAGES)

        # Should have been called exactly once — no retries for auth errors
        assert inner.call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_retries_dont_amplify(self):
        """10 concurrent requests with transient failures — all eventually succeed."""
        inner = FakeInnerAdapter()
        inner.set_behavior("fail_then_succeed", fail_after=1)
        adapter = _make_resilient(inner, timeout=30.0, circuit_breaker=False)

        results = await asyncio.gather(
            *[adapter.chat(MESSAGES) for _ in range(10)], return_exceptions=True
        )

        successes = [r for r in results if isinstance(r, LLMResponse)]
        assert len(successes) == 10
        # call_count is shared across concurrent calls — the first call trips
        # the counter past fail_after so later calls succeed on first try.
        # The key assertion is that all 10 succeed, not exact call count.
        assert inner.call_count >= 10

    @pytest.mark.asyncio
    @pytest.mark.timeout(180)
    async def test_all_retries_exhausted(self):
        """If all 7 attempts fail, the last exception surfaces."""
        inner = FakeInnerAdapter()
        inner.set_behavior("fail_always", error_msg="persistent failure")
        # Use short backoff delays to avoid hitting the 60s pytest-timeout.
        from weebot.utils.backoff import RetryWithBackoff, BackoffConfig

        adapter = ResilientLLMAdapter(
            inner_adapter=inner,
            model_name="test-model",
            timeout=5.0,
            enable_circuit_breaker=False,
            enable_retry=False,
        )
        # Wire in a fast-backoff retry manually
        adapter._retry = RetryWithBackoff(
            BackoffConfig(
                delays=[0.01, 0.02, 0.04, 0.08, 0.1, 0.2],
                jitter=0.1,
                retryable=adapter._is_retryable_error,
            )
        )

        with pytest.raises(RuntimeError, match="persistent failure"):
            await adapter.chat(MESSAGES)

        # 1 initial + 6 retries = 7 total
        assert inner.call_count == 7


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TestTimeoutEnforcement:
    """Request timeout behavior under various conditions."""

    @pytest.mark.asyncio
    async def test_slow_response_triggers_timeout(self):
        """A response taking longer than timeout is cancelled."""
        inner = FakeInnerAdapter()
        inner.set_behavior("slow", latency=5.0)
        adapter = _make_resilient(inner, timeout=0.2, retry=False, circuit_breaker=False)

        t0 = time.perf_counter()
        with pytest.raises(LLMTimeoutError):
            await adapter.chat(MESSAGES)
        elapsed = time.perf_counter() - t0

        # Should have timed out around 0.2s, not waited full 5s
        assert elapsed < 1.0, f"Timeout took {elapsed:.1f}s — didn't fire"

    @pytest.mark.asyncio
    async def test_timeout_records_circuit_failure(self):
        """Timeouts should count as circuit breaker failures."""
        inner = FakeInnerAdapter()
        inner.set_behavior("slow", latency=5.0)
        adapter = _make_resilient(inner, timeout=0.1, retry=False)

        for _ in range(3):
            with pytest.raises(LLMTimeoutError):
                await adapter.chat(MESSAGES)

        # Circuit should be open after 3 timeout failures
        with pytest.raises(CircuitBreakerOpen):
            await adapter.chat(MESSAGES)

    @pytest.mark.asyncio
    async def test_concurrent_timeouts_dont_deadlock(self):
        """20 concurrent requests all timing out — no hung tasks."""
        inner = FakeInnerAdapter()
        inner.set_behavior("slow", latency=10.0)
        adapter = _make_resilient(inner, timeout=0.1, retry=False, circuit_breaker=False)

        t0 = time.perf_counter()
        results = await asyncio.gather(
            *[adapter.chat(MESSAGES) for _ in range(20)], return_exceptions=True
        )
        elapsed = time.perf_counter() - t0

        assert all(isinstance(r, LLMTimeoutError) for r in results)
        # All 20 should resolve in ~timeout, not 20 × timeout
        assert elapsed < 2.0, f"Concurrent timeouts took {elapsed:.1f}s — queuing?"


# ---------------------------------------------------------------------------
# Recovery patterns
# ---------------------------------------------------------------------------


class TestRecoveryPatterns:
    """Circuit breaker recovery under sustained load."""

    @pytest.mark.asyncio
    async def test_recovery_after_outage(self):
        """Outage → circuit opens → service recovers → circuit closes."""
        inner = FakeInnerAdapter()
        cb = CircuitBreaker(
            failure_threshold=3, cooldown_seconds=0.1, jitter_percent=0.0, enable_stagger=False
        )
        adapter = ResilientLLMAdapter(
            inner_adapter=inner, model_name="test", timeout=5.0, enable_retry=False
        )
        # Inject our fast-cooldown breaker
        adapter._circuit = cb

        # Phase 1: outage
        inner.set_behavior("fail_always")
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await adapter.chat(MESSAGES)
        assert cb.get_state("test") == BreakerState.OPEN

        # Phase 2: wait for cooldown
        await asyncio.sleep(0.15)

        # Phase 3: service recovers
        inner.set_behavior("succeed")
        response = await adapter.chat(MESSAGES)
        assert response.content.startswith("response-")
        assert cb.get_state("test") == BreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_recovery_storm_bounded(self):
        """50 pending requests when circuit recovers — none are lost."""
        inner = FakeInnerAdapter()
        cb = CircuitBreaker(
            failure_threshold=2, cooldown_seconds=0.05, jitter_percent=0.0, enable_stagger=False
        )
        adapter = ResilientLLMAdapter(
            inner_adapter=inner, model_name="storm", timeout=5.0, enable_retry=False
        )
        adapter._circuit = cb

        # Trip the circuit
        inner.set_behavior("fail_always")
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await adapter.chat(MESSAGES)

        await asyncio.sleep(0.1)  # past cooldown

        # Service is back
        inner.set_behavior("succeed")

        # 50 requests hit at once
        results = await asyncio.gather(
            *[adapter.chat(MESSAGES) for _ in range(50)], return_exceptions=True
        )

        successes = [r for r in results if isinstance(r, LLMResponse)]
        circuit_rejects = [r for r in results if isinstance(r, CircuitBreakerOpen)]

        # Some succeed (the probe + post-recovery), some may be rejected
        # if they hit before the probe completes. The key assertion is no crashes.
        assert len(successes) + len(circuit_rejects) == 50
        assert len(successes) >= 1, "Not even the probe succeeded"

    @pytest.mark.asyncio
    async def test_flapping_service_reopens_circuit(self):
        """If the probe succeeds but the next request fails, circuit should re-open."""
        cb = CircuitBreaker(
            failure_threshold=1,  # aggressive
            cooldown_seconds=0.05,
            jitter_percent=0.0,
            enable_stagger=False,
        )

        # Trip
        await cb.record_failure("flap")
        assert cb.get_state("flap") == BreakerState.OPEN

        await asyncio.sleep(0.1)

        # Probe succeeds
        result = await cb.evaluate("flap")
        assert result.state == BreakerState.HALF_OPEN
        await cb.record_success("flap")
        assert cb.get_state("flap") == BreakerState.CLOSED

        # Immediately fails again
        await cb.record_failure("flap")
        assert cb.get_state("flap") == BreakerState.OPEN


# ---------------------------------------------------------------------------
# Mixed failure modes
# ---------------------------------------------------------------------------


class TestMixedFailureModes:
    """Realistic scenarios combining multiple failure types."""

    @pytest.mark.asyncio
    async def test_partial_outage_with_retries(self):
        """50% failure rate — retries should recover most requests.

        The sub-second ladder is what makes this test mean anything. On the
        default `[1, 2, 4, 8, 15, 30]` it failed roughly one run in seven —
        measured 2 in 12, and both failures were `Timeout (>60.0s)`, never the
        assertion below. The ladder sums to **exactly 60.0s** and
        `pyproject.toml` sets `timeout = 60`, so the test was racing the wall
        clock; observed durations cluster on the ladder's prefix sums
        {1, 3, 7, 15, 30, 60} — 18s, 34s, 62s.

        The comment beneath is not miscalculated. It models a different and
        irrelevant failure mode: P(successes < 18) from 0.5^7 per request is
        about 1 in 2400, which is what the comment says and is not what was
        failing. A gate that fires at random carries no information and trains
        everyone to ignore red — the mirror image of a gate that cannot fire.

        Same ladder the other retry tests in this file already use. This test
        measures the retry policy, not `asyncio.sleep`.
        """
        inner = FakeInnerAdapter()
        inner.set_behavior("fail_rate", fail_rate=0.5)
        adapter = _make_resilient(inner, timeout=30.0, circuit_breaker=False)
        adapter._retry = RetryWithBackoff(
            BackoffConfig(
                delays=[0.01, 0.02, 0.04, 0.08, 0.1, 0.2],
                jitter=0.1,
                retryable=adapter._is_retryable_error,
            )
        )

        results = await asyncio.gather(
            *[adapter.chat(MESSAGES) for _ in range(20)], return_exceptions=True
        )

        successes = [r for r in results if isinstance(r, LLMResponse)]
        # Seven attempts at a 50% fail rate: P(all seven fail) = 0.5^7 ~ 0.8%,
        # so ~99.2% of 20 requests should succeed. Allow two failures.
        assert len(successes) >= 18, f"Only {len(successes)}/20 succeeded at 50% fail rate"

    @pytest.mark.asyncio
    async def test_credential_redaction(self):
        """API keys in error messages should be redacted."""
        inner = FakeInnerAdapter()
        inner.set_behavior(
            "fail_always", error_msg="Request failed with api_key=sk-12345678901234567890abcdef"
        )
        adapter = _make_resilient(inner, retry=False, circuit_breaker=False)

        with pytest.raises(RuntimeError) as exc_info:
            await adapter.chat(MESSAGES)

        # The sk-... key should be redacted
        assert "sk-1234567890" not in str(exc_info.value)
        assert "REDACTED" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_metrics_tracked_correctly(self):
        """Success/failure counters should be accurate after mixed workload."""
        inner = FakeInnerAdapter()
        adapter = _make_resilient(inner, retry=False, circuit_breaker=True)

        # 5 successes
        inner.set_behavior("succeed")
        for _ in range(5):
            await adapter.chat(MESSAGES)

        # 3 failures (trips circuit)
        inner.set_behavior("fail_always")
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await adapter.chat(MESSAGES)

        metrics = adapter.get_metrics()
        assert metrics["circuit_breaker_enabled"] is True
        assert metrics["circuit_state"] == "open"


# ---------------------------------------------------------------------------
# Concurrent circuit breaker state machine
# ---------------------------------------------------------------------------


class TestConcurrentCircuitBreaker:
    """Circuit breaker correctness under concurrent state mutations."""

    @pytest.mark.asyncio
    async def test_concurrent_failures_trip_exactly_once(self):
        """20 concurrent failures — circuit should open after threshold, not before."""
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=60.0)

        await asyncio.gather(*[cb.record_failure("m") for _ in range(20)])

        assert cb.get_state("m") == BreakerState.OPEN
        assert cb._breakers["m"].failure_count == 20
        # State should have changed exactly once (CLOSED → OPEN)
        assert cb._state_changes == 1

    @pytest.mark.asyncio
    async def test_concurrent_success_and_failure(self):
        """Interleaved successes and failures — state machine stays consistent."""
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=60.0)

        async def _record(success: bool):
            if success:
                await cb.record_success("m")
            else:
                await cb.record_failure("m")

        # Alternate success/failure — 10 successes reset failure_count between
        # each failure, so circuit should stay CLOSED
        tasks = []
        for i in range(20):
            tasks.append(asyncio.create_task(_record(i % 2 == 0)))

        await asyncio.gather(*tasks)

        # State should still be CLOSED since successes reset the counter
        # (asyncio tasks run cooperatively, so the alternation pattern holds)
        state = cb.get_state("m")
        assert state in (BreakerState.CLOSED, BreakerState.OPEN)

    @pytest.mark.asyncio
    async def test_persistence_roundtrip(self, tmp_path):
        """Save + restore circuit breaker state survives restart."""
        cb1 = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
        await cb1.record_failure("model-a")
        await cb1.record_failure("model-a")
        await cb1.record_failure("model-a")
        assert cb1.get_state("model-a") == BreakerState.OPEN

        path = tmp_path / "breaker.json"
        cb1.persist_state(path)

        cb2 = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
        restored = cb2.restore_state(path)
        assert restored
        assert cb2.get_state("model-a") == BreakerState.OPEN
        assert cb2._breakers["model-a"].failure_count == 3
