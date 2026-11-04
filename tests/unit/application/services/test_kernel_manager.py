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

    async def start(self, session_id):
        kernel_id = f"k{len(self.started)}"
        self.started.append(session_id)
        self.state[kernel_id] = {}
        return KernelHandle(session_id, kernel_id)

    async def exec(self, handle, code, timeout):
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(self.delay)
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
