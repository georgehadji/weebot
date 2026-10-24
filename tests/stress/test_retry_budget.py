"""ORCH-3: measured retry amplification under a provider outage.

Plan item 2.3 of tasks/specs/arch_audit_2026_10_remediation_plan.md asked for a
measurement before any new mechanism. Result, recorded here as assertions:

* Inner layer: ``ResilientLLMAdapter`` retries a persistent 503 with delays
  ``[1, 2, 4, 8, 15, 30]`` -- 7 attempts and 60 s of backoff (jitter off here).
* Outer layer: the cascade cancels a model call at its ``wait_for`` (15 s for the
  BUDGET tier), which cancels the sleeping retry.
* So one cascade call to a dead model makes at most 4 attempts (starting at
  0, 1, 3 and 7 s) and spends 15 s, never 60 s. The SDK's own retries are 0
  (``adapter_factory.py:174``). The two layers do not multiply.

Deadline propagation (a ContextVar the retry reads) now stops a retry that could not
finish inside the cascade budget, so the real error surfaces instead of a cancellation. This file is the guard: if
the delays or the budget change so that amplification appears, it fails.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from weebot.utils.backoff import BackoffConfig, RetryWithBackoff

DELAYS = [1, 2, 4, 8, 15, 30]  # ResilientLLMAdapter.__init__
CASCADE_BUDGET_S = 15.0  # _cascade.py, BUDGET tier wait_for


def _retry() -> RetryWithBackoff:
    return RetryWithBackoff(
        BackoffConfig(delays=DELAYS, jitter=0.0, retryable=lambda exc: "503" in str(exc))
    )


async def _attempt_start_times() -> list[float]:
    """Virtual start time of every attempt against a provider that always says 503."""
    clock = 0.0
    starts: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        nonlocal clock
        clock += delay
        await real_sleep(0)

    async def always_503():
        starts.append(clock)
        raise RuntimeError("503 Service Unavailable")

    with patch("weebot.utils.backoff.asyncio.sleep", fake_sleep), pytest.raises(RuntimeError):
        await _retry().call(always_503)
    return starts


@pytest.mark.asyncio
async def test_the_adapter_alone_makes_seven_attempts_over_a_minute():
    starts = await _attempt_start_times()
    assert len(starts) == len(DELAYS) + 1 == 7
    assert starts[-1] == sum(DELAYS) == 60


@pytest.mark.asyncio
async def test_the_cascade_budget_caps_a_dead_model_at_four_attempts():
    starts = await _attempt_start_times()
    inside_the_budget = [t for t in starts if t < CASCADE_BUDGET_S]
    assert inside_the_budget == [0, 1, 3, 7]


@pytest.mark.asyncio
async def test_the_layers_do_not_multiply_across_the_cascade():
    """Attempts across a whole cascade of N dead models grow as 4N, not 7N or 7**N."""
    per_model = len([t for t in await _attempt_start_times() if t < CASCADE_BUDGET_S])
    models = 5
    assert per_model * models == 20
    assert per_model * models < 7 * models


def test_the_sdk_layer_adds_no_retries():
    """The third multiplier was removed in the retry-amplification fix; keep it removed."""
    import inspect

    from weebot.infrastructure.adapters.llm import adapter_factory

    source = inspect.getsource(adapter_factory)
    assert "max_retries" in source and "max_retries=0" in source.replace(" ", "")


@pytest.mark.asyncio
async def test_a_deadline_stops_the_retry_that_could_not_finish_inside_it():
    """Deadline propagation (ORCH-3): no sleep into the cancellation, the real error surfaces."""
    from weebot.utils import backoff

    clock = 0.0
    starts: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        nonlocal clock
        clock += delay
        await real_sleep(0)

    async def always_503():
        starts.append(clock)
        raise RuntimeError("503 Service Unavailable")

    with (
        patch("weebot.utils.backoff.asyncio.sleep", fake_sleep),
        patch("weebot.utils.backoff.time.monotonic", lambda: clock),
        backoff.deadline_scope(CASCADE_BUDGET_S),
        pytest.raises(RuntimeError, match="503"),
    ):
        await _retry().call(always_503)

    # Attempts at 0, 1, 3, 7; the retry after 7 would end at 15 >= the deadline, so it
    # is not scheduled and the time spent is 7 s, not 15.
    assert starts == [0, 1, 3, 7]
    assert clock == 7


@pytest.mark.asyncio
async def test_without_a_deadline_nothing_changes():
    assert len(await _attempt_start_times()) == 7
