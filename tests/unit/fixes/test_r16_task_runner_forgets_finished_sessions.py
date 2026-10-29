"""R16 (audit 2026-10-29): TaskRunner forgets a session's retry state when its run ends.

The retry budget and the flow factory lived in two dicts, cleared only when the budget was
spent. A run that succeeded, or was cancelled, kept both forever, and each factory holds
the run's tools and LLM client, so a long-lived web process grew with every session. One
record per session now goes when the session's current task ends.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.unit.application.services.test_task_runner_durable_state import (
    ExplodingFlow,
    MemoryRepo,
)
from weebot.application.services import task_runner as task_runner_module
from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.session import Session

_real_sleep = asyncio.sleep


class _OkFlow:
    def __init__(self, session, gate: asyncio.Event | None = None):
        self._session = session
        self._gate = gate

    async def run(self, prompt):
        if self._gate is not None:
            await self._gate.wait()
        return
        yield  # pragma: no cover - makes this an async generator

    def is_done(self):
        return True

    async def teardown(self):
        return None


async def _finish(runner: TaskRunner, sid: str) -> None:
    for _ in range(50):
        task = runner._tasks.get(sid)
        if task is None:
            return
        await asyncio.wait({task}, timeout=1)
        await _real_sleep(0)


def _state(runner: TaskRunner) -> dict:
    return runner._retries


@pytest.mark.asyncio
async def test_a_successful_run_leaves_nothing_behind():
    runner = TaskRunner(state_repo=MemoryRepo(), max_session_retries=2)
    await runner.start_session(Session(id="ok"), lambda s: _OkFlow(s))
    await _finish(runner, "ok")
    assert _state(runner) == {}


@pytest.mark.asyncio
async def test_a_cancelled_run_leaves_nothing_behind():
    runner = TaskRunner(state_repo=MemoryRepo(), max_session_retries=2)
    await runner.start_session(Session(id="c"), lambda s: _OkFlow(s, asyncio.Event()))
    await _real_sleep(0)
    assert "c" in _state(runner)
    assert await runner.cancel_session("c")
    await _finish(runner, "c")
    assert _state(runner) == {}


@pytest.mark.asyncio
async def test_spent_retries_leave_nothing_behind_but_a_pending_retry_keeps_its_state(
    monkeypatch,
):
    backoff_started = asyncio.Event()
    release = asyncio.Event()

    async def _gated(_delay):
        backoff_started.set()
        await release.wait()

    monkeypatch.setattr(task_runner_module.asyncio, "sleep", _gated)
    runner = TaskRunner(state_repo=MemoryRepo(), max_session_retries=1)
    await runner.start_session(Session(id="x"), lambda s: ExplodingFlow(s))

    await backoff_started.wait()  # the first attempt failed; its retry is scheduled
    assert _state(runner)["x"].remaining == 0

    monkeypatch.setattr(task_runner_module.asyncio, "sleep", _real_sleep)
    release.set()
    await _finish(runner, "x")
    assert _state(runner) == {}
