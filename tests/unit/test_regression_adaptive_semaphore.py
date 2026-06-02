"""Regression test: AdaptiveConcurrencyController semaphore replacement bug.

BUG: _adjust() replaced self._semaphore wholesale when scaling workers.
Any coroutine blocked on acquire() on the old semaphore was permanently
orphaned — release() operated on the new semaphore, so the old one's
waiters never woke up.

FIX: The semaphore is created once at max_workers and never replaced.
Scaling down is advisory (current_workers is updated for reporting).
"""
from __future__ import annotations

import asyncio

import pytest

from weebot.core.adaptive_concurrency import AdaptiveConcurrencyController


@pytest.mark.asyncio
async def test_semaphore_not_replaced_during_scale():
    """Semaphore identity must not change when current_workers is adjusted."""
    ctrl = AdaptiveConcurrencyController(
        min_workers=2,
        max_workers=10,
        cpu_threshold=0.0,    # force scale-down on any CPU
        memory_threshold=0.0,  # force scale-down on any memory
        adjustment_interval=999,
    )

    sem_before = ctrl._semaphore

    # Manually trigger _adjust to simulate scaling
    ctrl.current_workers = 8  # simulate having scaled up previously
    await ctrl._adjust()

    sem_after = ctrl._semaphore

    # The semaphore object must be the same instance — replacing it
    # would orphan any coroutines blocked on the old one.
    assert sem_before is sem_after, (
        "Semaphore was replaced during _adjust() — blocked waiters would be orphaned"
    )


@pytest.mark.asyncio
async def test_acquire_release_uses_same_semaphore_after_scale():
    """acquire()/release() must operate on the current semaphore after scaling."""
    ctrl = AdaptiveConcurrencyController(
        min_workers=2,
        max_workers=5,
        cpu_threshold=0.0,
        memory_threshold=0.0,
        adjustment_interval=999,
    )

    # Acquire one slot
    await ctrl.acquire()
    ctrl.current_workers = 3  # simulate scale
    await ctrl._adjust()

    # Release must go to the same semaphore
    ctrl.release()

    # Should be able to acquire again (proving release worked)
    await ctrl.acquire()
    ctrl.release()


@pytest.mark.asyncio
async def test_max_workers_never_exceeded():
    """Semaphore must not allow more than max_workers concurrent acquisitions."""
    ctrl = AdaptiveConcurrencyController(
        min_workers=1,
        max_workers=3,
        cpu_threshold=100.0,   # never scale down
        memory_threshold=100.0,
        adjustment_interval=999,
    )

    acquired = 0
    max_observed = 0

    async def worker():
        nonlocal acquired, max_observed
        await ctrl.acquire()
        acquired += 1
        max_observed = max(max_observed, acquired)
        await asyncio.sleep(0.01)
        acquired -= 1
        ctrl.release()

    tasks = [asyncio.create_task(worker()) for _ in range(10)]
    await asyncio.gather(*tasks)

    assert max_observed <= 3, (
        f"max_workers=3 but {max_observed} tasks ran concurrently"
    )
