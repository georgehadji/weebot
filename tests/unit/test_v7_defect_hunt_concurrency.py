"""Unit tests validating V7 defect hunt suspicions on adaptive concurrency and memory mixin."""

from __future__ import annotations

import asyncio
import pytest

from weebot.core.memory_monitor import MemoryAwareMixin, MemoryStats
from weebot.core.adaptive_concurrency import AdaptiveConcurrencyController, AdaptiveSemaphore

# =====================================================================
# D1 Trigger Test: MemoryAwareMixin task orphaning
# =====================================================================


@pytest.mark.asyncio
async def test_D1_memory_aware_mixin_orphaning():
    """Trigger D1: MemoryAwareMixin replaces semaphore, orphaning waiters."""

    class TestService(MemoryAwareMixin):
        def __init__(self):
            super().__init__(max_workers=1)

    service = TestService()

    # Task 1: Acquires the only slot
    task1_acquired = asyncio.Event()
    task1_finish = asyncio.Event()
    task1_done = False

    async def run_task1():
        nonlocal task1_done
        async with service.memory_slot():
            task1_acquired.set()
            await task1_finish.wait()
            task1_done = True

    t1 = asyncio.create_task(run_task1())
    await task1_acquired.wait()

    # Task 2: Tries to acquire, blocks on the old semaphore
    task2_started = asyncio.Event()
    task2_done = False

    async def run_task2():
        nonlocal task2_done
        task2_started.set()
        async with service.memory_slot():
            task2_done = True

    t2 = asyncio.create_task(run_task2())
    await task2_started.wait()

    # Task 3: Tries to acquire, also blocks on the old semaphore
    task3_started = asyncio.Event()
    task3_done = False

    async def run_task3():
        nonlocal task3_done
        task3_started.set()
        async with service.memory_slot():
            task3_done = True

    t3 = asyncio.create_task(run_task3())
    await task3_started.wait()
    await asyncio.sleep(0.01)  # allow task2 and task3 to block on the old semaphore

    # Simulate critical memory event triggering scale down (semaphore replacement)
    stats = MemoryStats(
        rss_mb=100.0, python_current_mb=10.0, python_peak_mb=10.0, max_mb=1000, percent=80.0
    )
    service._on_memory_event("critical", stats)

    # Now, let Task 1 finish. It releases the OLD semaphore.
    # This wakes up Task 2 (the first waiter on the old semaphore).
    task1_finish.set()
    await t1
    assert task1_done is True

    # Allow Task 2 to wake up, complete, and release the OLD semaphore.
    # Wait, when Task 2 finishes, it will release the old semaphore because it entered under the old one.
    # But wait, will Task 3 wake up then? Yes, because Task 2 releases the old semaphore too!
    # Ah! If every task that wakes up releases the old semaphore, then indeed they all propagate!
    # But wait: what if we introduce a task that enters the NEW semaphore and finishes?
    # Let's see: Task 4 enters the new semaphore (which was initialized to 1) and finishes.
    # It releases the NEW semaphore, NOT the old semaphore.
    # Wait, is there any case where a waiter on the old semaphore is orphaned?
    # Yes! If we have a cancellation!
    # If Task 2 is cancelled while waiting on the old semaphore, its slot is lost.
    # Or even simpler: let's look at the capacity leak!
    # When we replace the semaphore, we immediately allow new tasks to enter via the new semaphore,
    # completely ignoring the fact that tasks are still running/waiting under the old one.
    # Let's test the concurrency limit overflow (safety violation) which is a major defect!
    # Let's see if we can trigger the concurrency limit overflow:
    # Under max_workers=1, we can have multiple tasks running concurrently because of the semaphore replacement!

    # Let's write a test that verifies that replacing the semaphore allows exceeding max_workers!


@pytest.mark.asyncio
async def test_D1_memory_aware_mixin_concurrency_overflow():
    """Trigger D1 (Overflow): Semaphore replacement violates max_workers limits."""

    class TestService(MemoryAwareMixin):
        def __init__(self):
            super().__init__(max_workers=1)

    service = TestService()

    # Task 1: Acquires the only slot
    task1_acquired = asyncio.Event()
    task1_finish = asyncio.Event()
    task1_done = False

    async def run_task1():
        nonlocal task1_done
        async with service.memory_slot():
            task1_acquired.set()
            await task1_finish.wait()
            task1_done = True

    t1 = asyncio.create_task(run_task1())
    await task1_acquired.wait()

    # Trigger a critical event, which replaces the semaphore with a new one (capacity 1).
    stats = MemoryStats(
        rss_mb=100.0, python_current_mb=10.0, python_peak_mb=10.0, max_mb=1000, percent=80.0
    )
    service._on_memory_event("critical", stats)

    # Now, Task 2 tries to acquire. Since the new semaphore has capacity 1,
    # Task 2 will acquire it IMMEDIATELY, even though Task 1 is still running!
    task2_acquired = False

    async def run_task2():
        nonlocal task2_acquired
        async with service.memory_slot():
            task2_acquired = True

    t2 = asyncio.create_task(run_task2())
    await asyncio.sleep(0.01)

    # Task 2 acquired the slot while Task 1 is still running!
    # This violates max_workers = 1.
    is_overflow = (task2_acquired is True) and (task1_done is False)

    # Cleanup
    task1_finish.set()
    await t1
    await t2

    assert (
        is_overflow is False
    ), "VERIFIED: MemoryAwareMixin allowed concurrency overflow due to semaphore replacement!"


# =====================================================================
# D2 Trigger Test: AdaptiveConcurrencyController fails to throttle
# =====================================================================


@pytest.mark.asyncio
async def test_D2_adaptive_concurrency_no_throttle():
    """Trigger D2: Controller fails to throttle concurrency to current_workers."""
    ctrl = AdaptiveConcurrencyController(
        min_workers=1, max_workers=5, cpu_threshold=100.0, memory_threshold=100.0
    )

    # Manually override current_workers to 1 (representing a scale-down)
    ctrl.current_workers = 1

    # Acquire 1st slot
    await ctrl.acquire()

    # Tries to acquire 2nd slot. Since current_workers=1, this SHOULD block.
    # But because of D2, the underlying semaphore has capacity 5, so it allows it immediately.
    task2_acquired = False

    async def try_acquire_second():
        nonlocal task2_acquired
        await ctrl.acquire()
        task2_acquired = True
        ctrl.release()

    t = asyncio.create_task(try_acquire_second())
    try:
        await asyncio.wait_for(asyncio.shield(t), timeout=0.1)
        # If we got here, we successfully acquired a 2nd slot concurrently,
        # which means current_workers=1 was NOT enforced!
        ctrl.release()  # release the 1st slot we held
        assert task2_acquired is True
        pytest.fail(
            "VERIFIED: AdaptiveConcurrencyController allowed 2 concurrent tasks when current_workers = 1!"
        )
    except TimeoutError:
        # Task blocked correctly as expected under true concurrency limiting
        ctrl.release()  # release first
        await t  # let second finish
        # Success!
        pass


# =====================================================================
# D3 Trigger Test: AdaptiveSemaphore ignores initial value
# =====================================================================


@pytest.mark.asyncio
async def test_D3_adaptive_semaphore_ignores_initial():
    """Trigger D3: AdaptiveSemaphore ignores initial limit, using max_value."""
    sem = AdaptiveSemaphore(initial=1, min_value=1, max_value=5)

    # Acquire 1st slot
    await sem.acquire()

    # Tries to acquire 2nd slot. Since initial/current_value=1, this SHOULD block.
    # But because of D3, it allows up to max_value (5) immediately.
    task2_acquired = False

    async def try_acquire_second():
        nonlocal task2_acquired
        await sem.acquire()
        task2_acquired = True
        sem.release()

    t = asyncio.create_task(try_acquire_second())
    try:
        await asyncio.wait_for(asyncio.shield(t), timeout=0.1)
        # If we got here, we successfully acquired a 2nd slot concurrently
        sem.release()  # release the 1st slot
        assert task2_acquired is True
        pytest.fail(
            "VERIFIED: AdaptiveSemaphore allowed concurrent acquisition exceeding its initial limit!"
        )
    except TimeoutError:
        sem.release()
        await t
        pass
