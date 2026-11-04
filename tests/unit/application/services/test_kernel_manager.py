"""KernelManager: one kernel per session, four at most, least recently used out (H17)."""

from __future__ import annotations

import asyncio

import pytest

from weebot.application.ports.kernel_port import KernelHandle, KernelPort, KernelResult
from weebot.application.services.kernel_manager import KernelManager


class FakeKernels(KernelPort):
    """Each kernel is a dict of variables; ``x = N`` sets one, ``x`` reads it."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.state: dict[str, dict] = {}
        self.running = 0
        self.max_running = 0
        self.delay = 0.0
        self.die_on = ""
        self.vanish_next = ""  # the next exec finds its kernel already gone; the code never ran
        self.fail_start = False
        self.start_delay: dict[str, float] = {}

    async def start(self, session_id):
        if self.fail_start:
            raise RuntimeError("kernel did not start")
        await asyncio.sleep(self.start_delay.get(session_id, 0.0))
        kernel_id = f"k{len(self.started)}"
        self.started.append(session_id)
        self.state[kernel_id] = {}
        return KernelHandle(session_id, kernel_id)

    async def exec(self, handle, code, timeout, on_rpc=None):
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            if self.vanish_next:
                error, self.vanish_next = self.vanish_next, ""
                return KernelResult(error=error, died=True, ran=False)
            await asyncio.sleep(30 if code == "hang" else self.delay)
            if code == self.die_on:
                return KernelResult(error="The kernel stopped (exit code 9).", died=True)
            if "=" in code:
                name, value = (p.strip() for p in code.split("="))
                self.state[handle.kernel_id][name] = value
                return KernelResult()
            return KernelResult(stdout=str(self.state[handle.kernel_id].get(code, "<unset>")))
        finally:
            self.running -= 1

    async def stop(self, handle):
        self.stopped.append(handle.session_id)


@pytest.fixture
def backend():
    return FakeKernels()


@pytest.fixture
def manager(backend):
    return KernelManager(backend)


@pytest.mark.asyncio
async def test_state_persists_for_a_session_and_not_across_sessions(manager):
    await manager.run("a", "x = 1", 5)

    same = await manager.run("a", "x", 5)
    other = await manager.run("b", "x", 5)

    assert same.result.stdout == "1" and other.result.stdout == "<unset>"


@pytest.mark.asyncio
async def test_one_kernel_is_started_per_session(manager, backend):
    for _ in range(3):
        await manager.run("a", "x", 5)

    assert backend.started == ["a"]


@pytest.mark.asyncio
async def test_the_fifth_kernel_evicts_the_least_recently_used(manager, backend):
    for session in ("a", "b", "c", "d"):
        await manager.run(session, "x = 1", 5)
    await manager.run("a", "x", 5)  # a is now the most recent; b is the oldest

    await manager.run("e", "x = 1", 5)

    assert backend.stopped == ["b"]
    assert manager.live_sessions == ["c", "d", "a", "e"]


@pytest.mark.asyncio
async def test_an_evicted_session_starts_anew_and_is_told_why(manager):
    await manager.run("a", "x = 1", 5)
    for session in ("b", "c", "d", "e"):
        await manager.run(session, "x = 1", 5)  # e pushes a out

    back = await manager.run("a", "x", 5)

    assert back.result.stdout == "<unset>"
    assert "make room" in back.notice
    assert (await manager.run("a", "x", 5)).notice == ""  # said once


@pytest.mark.asyncio
async def test_a_busy_kernel_is_not_evicted(backend):
    manager = KernelManager(backend, max_kernels=2)
    backend.delay = 0.2
    busy = [asyncio.create_task(manager.run(s, "x = 1", 5)) for s in ("a", "b")]
    await asyncio.sleep(0.05)

    with pytest.raises(RuntimeError, match="busy"):
        await manager.run("c", "x = 1", 5)

    await asyncio.gather(*busy)
    assert backend.stopped == []


@pytest.mark.asyncio
async def test_calls_for_one_session_run_one_at_a_time(manager, backend):
    backend.delay = 0.05

    await asyncio.gather(*(manager.run("a", f"v{i} = {i}", 5) for i in range(4)))

    assert backend.max_running == 1


@pytest.mark.asyncio
async def test_calls_for_different_sessions_run_together(manager, backend):
    backend.delay = 0.05

    await asyncio.gather(*(manager.run(s, "x = 1", 5) for s in ("a", "b", "c")))

    assert backend.max_running == 3


@pytest.mark.asyncio
async def test_reset_discards_the_variables_without_a_notice(manager, backend):
    await manager.run("a", "x = 1", 5)

    after = await manager.run("a", "x", 5, reset=True)

    assert after.result.stdout == "<unset>" and after.notice == ""
    assert backend.stopped == ["a"] and backend.started == ["a", "a"]


@pytest.mark.asyncio
async def test_a_kernel_that_dies_is_dropped_and_the_next_call_says_so(manager, backend):
    await manager.run("a", "x = 1", 5)
    backend.die_on = "boom"

    died = await manager.run("a", "boom", 5)
    assert died.result.died and manager.live_sessions == []

    backend.die_on = ""
    again = await manager.run("a", "x", 5)
    assert again.result.stdout == "<unset>" and "exit code 9" in again.notice


@pytest.mark.asyncio
async def test_stop_session_stops_its_kernel_and_forgets_the_loss(manager, backend):
    await manager.run("a", "x = 1", 5)

    assert await manager.stop_session("a") == 1
    assert await manager.stop_session("a") == 0
    assert backend.stopped == ["a"]
    assert (await manager.run("a", "x", 5)).notice == ""


@pytest.mark.asyncio
async def test_stopping_a_session_during_a_call_ends_it_without_a_stale_kernel(manager, backend):
    backend.delay = 0.1
    running = asyncio.create_task(manager.run("a", "x = 1", 5))
    await asyncio.sleep(0.03)

    await manager.stop_session("a")
    await running

    assert manager.live_sessions == []


@pytest.mark.asyncio
async def test_stop_all_stops_every_kernel(manager, backend):
    for session in ("a", "b"):
        await manager.run(session, "x = 1", 5)

    await manager.stop_all()

    assert sorted(backend.stopped) == ["a", "b"] and manager.live_sessions == []


@pytest.mark.asyncio
async def test_a_cancelled_call_drops_its_kernel_and_the_next_call_says_so(manager, backend):
    await manager.run("a", "x = 1", 5)
    hung = asyncio.create_task(manager.run("a", "hang", 5))
    await asyncio.sleep(0.03)

    hung.cancel()
    with pytest.raises(asyncio.CancelledError):
        await hung

    assert manager.live_sessions == [] and backend.stopped == ["a"]
    again = await manager.run("a", "x", 5)
    assert again.result.stdout == "<unset>" and "cancelled" in again.notice


@pytest.mark.asyncio
async def test_a_call_whose_kernel_was_gone_before_it_ran_is_run_on_a_fresh_one(manager, backend):
    await manager.run("a", "x = 1", 5)
    backend.vanish_next = "The kernel stopped (memory limit of 1024 MB exceeded)."

    run = await manager.run("a", "x = 2", 5)

    assert run.result.success and backend.started == ["a", "a"]
    assert "memory limit" in run.notice
    assert (await manager.run("a", "x", 5)).result.stdout == "2"


@pytest.mark.asyncio
async def test_a_kernel_that_will_not_start_leaves_no_slot_and_keeps_the_notice(manager, backend):
    await manager.run("a", "x = 1", 5)
    backend.die_on = "boom"
    await manager.run("a", "boom", 5)
    backend.fail_start = True

    with pytest.raises(RuntimeError, match="did not start"):
        await manager.run("a", "x", 5)
    assert manager.live_sessions == []

    backend.fail_start = False
    assert "exit code 9" in (await manager.run("a", "x", 5)).notice


@pytest.mark.asyncio
async def test_a_slow_start_for_one_session_does_not_hold_up_another(manager, backend):
    await manager.run("b", "x = 1", 5)
    backend.start_delay["slow"] = 0.3
    slow = asyncio.create_task(manager.run("slow", "x = 1", 5))
    await asyncio.sleep(0.03)

    await asyncio.wait_for(manager.run("b", "x", 5), timeout=0.15)

    assert not slow.done()
    await slow


@pytest.mark.asyncio
async def test_a_slot_with_a_waiting_call_is_not_evicted(backend):
    manager = KernelManager(backend, max_kernels=2)
    backend.delay = 0.2
    await manager.run("b", "x = 1", 5)
    first = asyncio.create_task(manager.run("a", "x = 1", 5))
    queued = asyncio.create_task(manager.run("a", "y = 1", 5))
    await asyncio.sleep(0.05)

    await manager.run("c", "x = 1", 5)  # b is the idle one

    await asyncio.gather(first, queued)
    assert backend.stopped == ["b"]


def test_the_manager_can_be_used_from_one_event_loop_after_another(backend):
    manager = KernelManager(backend)

    async def contended():
        await asyncio.gather(*(manager.run("a", f"v{i} = {i}", 5) for i in range(3)))

    backend.delay = 0.02
    asyncio.run(contended())  # the slot's lock is waited on, so it binds to this loop
    asyncio.run(contended())  # a different loop must not meet the old lock

    assert manager.live_sessions == ["a"]
