"""Tests for AsyncEventBus per-subscriber timeout (ARCH-AUDIT-V2 A3).

Verifies:
  1. A handler that exceeds the timeout is logged as timed out.
  2. A fast handler still completes when a slow handler times out.
  3. Timeout=None disables the timeout (handler runs to completion).
  4. Domain events also respect the timeout.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from weebot.infrastructure.event_bus import AsyncEventBus
from weebot.domain.models.event import AgentEvent, DomainEvent


@pytest.fixture
def fast_event() -> AgentEvent:
    """A minimal AgentEvent for testing."""
    from weebot.domain.models.event import MessageEvent
    return MessageEvent(role="user", message="test")


@pytest.fixture
def domain_event() -> DomainEvent:
    from weebot.domain.models.event import FactDiscovered
    return FactDiscovered(session_id="test", key="k", value="v")


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: Timeout — slow handler times out, fast handler completes
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_slow_handler_times_out_fast_handler_succeeds(
    fast_event: AgentEvent, caplog: pytest.LogCaptureFixture,
):
    """A handler taking 60s must time out with a 0.05s timeout;
    a concurrent 0s handler must still complete."""
    bus = AsyncEventBus(handler_timeout=0.05)
    slow_done = fast_done = False

    async def slow_handler(_event: AgentEvent) -> None:
        nonlocal slow_done
        await asyncio.sleep(60)
        slow_done = True

    async def fast_handler(_event: AgentEvent) -> None:
        nonlocal fast_done
        fast_done = True

    bus.subscribe(slow_handler)
    bus.subscribe(fast_handler)

    with caplog.at_level(logging.WARNING, logger="weebot.infrastructure.event_bus"):
        await bus.publish(fast_event)

    # Fast handler must have completed
    assert fast_done, "Fast handler should have completed"
    # Slow handler must NOT have completed (timed out)
    assert not slow_done, "Slow handler should not have completed (timed out)"
    # Timeout must be logged
    assert "timed out after" in caplog.text, "Timeout warning must be logged"


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: No timeout — handler runs to completion
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_no_timeout_when_disabled(fast_event: AgentEvent):
    """When handler_timeout is None, a slow handler must complete."""
    bus = AsyncEventBus(handler_timeout=None)
    done = False

    async def slow_handler(_event: AgentEvent) -> None:
        nonlocal done
        await asyncio.sleep(0.02)
        done = True

    bus.subscribe(slow_handler)
    await bus.publish(fast_event)
    assert done, "Handler should have completed (timeout disabled)"


# ═════════════════════════════════════════════════════════════════════════════
# Test 3: Domain event timeout
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_domain_event_timeout(
    domain_event: DomainEvent, caplog: pytest.LogCaptureFixture,
):
    """Domain events must also respect the per-subscriber timeout."""
    bus = AsyncEventBus(handler_timeout=0.05)
    done = False

    async def slow_handler(_event: DomainEvent) -> None:
        nonlocal done
        await asyncio.sleep(60)
        done = True

    bus.subscribe_domain(slow_handler)

    with caplog.at_level(logging.WARNING, logger="weebot.infrastructure.event_bus"):
        await bus.publish_domain_event(domain_event)

    assert not done, "Domain handler should have timed out"
    assert "timed out after" in caplog.text, "Domain timeout warning must be logged"


# ═════════════════════════════════════════════════════════════════════════════
# Test 4: Handler error does not crash publish
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_handler_exception_does_not_crash_bus(fast_event: AgentEvent):
    """A handler that raises should not prevent other handlers from running."""
    bus = AsyncEventBus(handler_timeout=0.05)
    good_done = False

    async def crashing_handler(_event: AgentEvent) -> None:
        raise ValueError("expected crash")

    async def good_handler(_event: AgentEvent) -> None:
        nonlocal good_done
        good_done = True

    bus.subscribe(crashing_handler)
    bus.subscribe(good_handler)

    # Must not raise
    await bus.publish(fast_event)
    assert good_done, "Good handler should have completed despite crash in another"
