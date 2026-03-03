"""Tests for CircuitBreaker implementation.

Phase 2 Deliverable: 10+ tests for CircuitBreaker
"""
from __future__ import annotations

import asyncio
import time
import pytest
from datetime import datetime

from weebot.core.circuit_breaker import (
    CircuitBreaker,
    BreakerState,
    BreakerResult,
)


class TestCircuitBreakerBasics:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        """Circuit starts in CLOSED state (healthy)."""
        cb = CircuitBreaker()
        result = await cb.evaluate("test_entity")

        assert result.state == BreakerState.CLOSED
        assert result.allowed is True
        assert result.entity_id == "test_entity"

    @pytest.mark.asyncio
    async def test_failure_threshold_opens_circuit(self):
        """After N failures, circuit opens."""
        cb = CircuitBreaker(failure_threshold=3)

        # Record 3 failures
        for _ in range(3):
            await cb.record_failure("test_entity")

        result = await cb.evaluate("test_entity")
        assert result.state == BreakerState.OPEN
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """Success in CLOSED state resets failure counter."""
        cb = CircuitBreaker(failure_threshold=3)

        # 2 failures
        await cb.record_failure("test_entity")
        await cb.record_failure("test_entity")

        # Success resets
        await cb.record_success("test_entity")

        # Should still be closed (failure count reset)
        result = await cb.evaluate("test_entity")
        assert result.state == BreakerState.CLOSED
        assert result.allowed is True


class TestCircuitBreakerStateMachine:
    """State machine transition tests."""

    @pytest.mark.asyncio
    async def test_closed_to_open_transition(self):
        """CLOSED -> OPEN after threshold failures."""
        cb = CircuitBreaker(failure_threshold=2)

        assert cb.get_state("entity") == BreakerState.CLOSED

        await cb.record_failure("entity")
        assert cb.get_state("entity") == BreakerState.CLOSED

        await cb.record_failure("entity")
        assert cb.get_state("entity") == BreakerState.OPEN

    @pytest.mark.asyncio
    async def test_open_to_half_open_transition(self):
        """OPEN -> HALF_OPEN after cooldown."""
        cb = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.1  # Short for testing
        )

        # Open the circuit
        await cb.record_failure("entity")
        assert cb.get_state("entity") == BreakerState.OPEN

        # Wait for cooldown
        await asyncio.sleep(0.15)

        # Should transition to HALF_OPEN
        result = await cb.evaluate("entity")
        assert result.state == BreakerState.HALF_OPEN
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self):
        """HALF_OPEN -> CLOSED on success threshold."""
        cb = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.1,
            success_threshold=1
        )

        # Open then transition to HALF_OPEN
        await cb.record_failure("entity")
        await asyncio.sleep(0.15)
        await cb.evaluate("entity")  # Triggers HALF_OPEN

        assert cb.get_state("entity") == BreakerState.HALF_OPEN

        # Success should close it
        await cb.record_success("entity")
        assert cb.get_state("entity") == BreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        """HALF_OPEN -> OPEN on probe failure."""
        cb = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.1
        )

        # Open then transition to HALF_OPEN
        await cb.record_failure("entity")
        await asyncio.sleep(0.15)
        await cb.evaluate("entity")

        assert cb.get_state("entity") == BreakerState.HALF_OPEN

        # Failure should reopen
        await cb.record_failure("entity")
        assert cb.get_state("entity") == BreakerState.OPEN


class TestCircuitBreakerMultipleEntities:
    """Tests for per-entity isolation."""

    @pytest.mark.asyncio
    async def test_entities_are_isolated(self):
        """Failure in one entity doesn't affect others."""
        cb = CircuitBreaker(failure_threshold=2)

        # Fail entity A twice
        await cb.record_failure("entity_a")
        await cb.record_failure("entity_a")

        # Entity A is open
        assert cb.get_state("entity_a") == BreakerState.OPEN

        # Entity B is still closed
        assert cb.get_state("entity_b") == BreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_get_all_states(self):
        """Get state snapshot for all entities."""
        cb = CircuitBreaker(failure_threshold=1)

        await cb.record_failure("entity_a")
        await cb.record_failure("entity_b")

        states = cb.get_all_states()
        assert states["entity_a"] == BreakerState.OPEN
        assert states["entity_b"] == BreakerState.OPEN


class TestCircuitBreakerManualOverride:
    """Tests for manual reset functionality."""

    @pytest.mark.asyncio
    async def test_manual_reset(self):
        """Manual reset opens circuit immediately."""
        cb = CircuitBreaker(failure_threshold=1)

        await cb.record_failure("entity")
        assert cb.get_state("entity") == BreakerState.OPEN

        await cb.reset("entity")
        assert cb.get_state("entity") == BreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_reset_nonexistent_entity(self):
        """Reset of unknown entity is safe."""
        cb = CircuitBreaker()

        # Should not raise
        await cb.reset("unknown_entity")
        assert cb.get_state("unknown_entity") == BreakerState.CLOSED


class TestCircuitBreakerConfiguration:
    """Configuration validation tests."""

    def test_invalid_failure_threshold(self):
        """Failure threshold must be >= 1."""
        with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
            CircuitBreaker(failure_threshold=0)

    def test_invalid_cooldown(self):
        """Cooldown must be > 0."""
        with pytest.raises(ValueError, match="cooldown_seconds must be > 0"):
            CircuitBreaker(cooldown_seconds=0)

    @pytest.mark.asyncio
    async def test_custom_thresholds(self):
        """Custom thresholds work correctly."""
        cb = CircuitBreaker(
            failure_threshold=5,
            success_threshold=3,
            cooldown_seconds=0.1
        )

        # Need 5 failures to open
        for i in range(4):
            await cb.record_failure("entity")
            assert cb.get_state("entity") == BreakerState.CLOSED

        await cb.record_failure("entity")
        assert cb.get_state("entity") == BreakerState.OPEN


class TestCircuitBreakerResultDetails:
    """Tests for result metadata."""

    @pytest.mark.asyncio
    async def test_result_includes_failure_count(self):
        """Result includes current failure count."""
        cb = CircuitBreaker(failure_threshold=5)

        await cb.record_failure("entity")
        await cb.record_failure("entity")

        result = await cb.evaluate("entity")
        assert result.failure_count == 2

    @pytest.mark.asyncio
    async def test_result_includes_last_failure_time(self):
        """OPEN result includes last failure timestamp (monotonic clock)."""
        cb = CircuitBreaker(failure_threshold=1)

        before = time.monotonic()
        await cb.record_failure("entity")
        after = time.monotonic()

        result = await cb.evaluate("entity")
        assert result.state == BreakerState.OPEN
        assert before <= result.last_failure_time <= after

    @pytest.mark.asyncio
    async def test_result_includes_reason(self):
        """Result includes human-readable reason."""
        cb = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=60
        )

        await cb.record_failure("entity")
        result = await cb.evaluate("entity")

        assert result.state == BreakerState.OPEN
        assert "Circuit open" in result.reason
        assert "until probe" in result.reason


class TestCircuitBreakerConcurrency:
    """Concurrency safety tests."""

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Circuit breaker is safe under concurrent access."""
        cb = CircuitBreaker(failure_threshold=100)

        async def record_failures():
            for _ in range(10):
                await cb.record_failure("entity")
                await asyncio.sleep(0.001)

        # Run 10 concurrent recorders
        await asyncio.gather(*[record_failures() for _ in range(10)])

        # Should have exactly 100 failures
        result = await cb.evaluate("entity")
        assert result.state == BreakerState.OPEN
        assert result.failure_count == 100

    @pytest.mark.asyncio
    async def test_concurrent_evaluations(self):
        """Concurrent evaluations are safe."""
        cb = CircuitBreaker(failure_threshold=5)

        # Open the circuit
        for _ in range(5):
            await cb.record_failure("entity")

        # Concurrent evaluations should all see OPEN
        results = await asyncio.gather(*[
            cb.evaluate("entity") for _ in range(10)
        ])

        assert all(r.state == BreakerState.OPEN for r in results)
        assert all(r.allowed is False for r in results)


class TestCircuitBreakerEventBroker:
    """EventBroker integration tests."""

    @pytest.mark.asyncio
    async def test_state_change_events(self):
        """State changes publish events to EventBroker."""
        events = []

        class MockEventBroker:
            async def publish(self, event_type, entity_id, data):
                events.append({
                    "event_type": event_type,
                    "entity_id": entity_id,
                    "data": data
                })

        broker = MockEventBroker()
        cb = CircuitBreaker(
            failure_threshold=1,
            event_broker=broker
        )

        await cb.record_failure("entity")

        assert len(events) == 1
        assert events[0]["event_type"] == "circuit_breaker_state_change"
        assert events[0]["data"]["old_state"] == "closed"
        assert events[0]["data"]["new_state"] == "open"


# Performance test
@pytest.mark.asyncio
async def test_circuit_breaker_performance():
    """Circuit breaker handles high throughput."""
    cb = CircuitBreaker(failure_threshold=1000)

    start = asyncio.get_event_loop().time()

    # 1000 evaluations
    for i in range(1000):
        await cb.evaluate(f"entity_{i}")

    elapsed = asyncio.get_event_loop().time() - start

    # Should complete in reasonable time (< 1s for 1000 ops)
    assert elapsed < 1.0


# Integration-style test
@pytest.mark.asyncio
async def test_full_lifecycle_simulation():
    """Simulate realistic circuit breaker lifecycle."""
    cb = CircuitBreaker(
        failure_threshold=3,
        cooldown_seconds=0.1,
        success_threshold=2
    )
    entity = "api_service"

    # Phase 1: Normal operation
    for _ in range(5):
        result = await cb.evaluate(entity)
        assert result.allowed
        await cb.record_success(entity)

    # Phase 2: Degradation
    for _ in range(3):
        await cb.record_failure(entity)

    result = await cb.evaluate(entity)
    assert result.state == BreakerState.OPEN
    assert not result.allowed

    # Phase 3: Recovery attempt (wait for cooldown)
    await asyncio.sleep(0.15)
    result = await cb.evaluate(entity)
    assert result.state == BreakerState.HALF_OPEN

    # Phase 4: Successful recovery
    await cb.record_success(entity)
    await cb.record_success(entity)  # success_threshold=2

    result = await cb.evaluate(entity)
    assert result.state == BreakerState.CLOSED
    assert result.allowed
