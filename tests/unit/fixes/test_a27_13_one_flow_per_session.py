"""A13: two concurrent answers to one WAITING session both passed the status check and
started two flows, because load -> check -> save -> start was not atomic."""

from __future__ import annotations

import asyncio

import pytest

from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.event import DoneEvent
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


class _SlowRepo(InMemoryStateRepository):
    """Yields to the event loop on each read and write, as a real database does."""

    async def load_session(self, session_id):
        await asyncio.sleep(0)
        return await super().load_session(session_id)

    async def save_session(self, session):
        await asyncio.sleep(0)
        await super().save_session(session)


class _Flow:
    def __init__(self, release: asyncio.Event) -> None:
        self._release = release

    async def run(self, prompt: str):
        await self._release.wait()
        yield DoneEvent()

    def is_done(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass


async def _runner(status: SessionStatus):
    repo = _SlowRepo()
    await repo.save_session(Session(id="s1", user_id="u", agent_id="a", status=status,
                                    context={"last_prompt": "task"}))
    return TaskRunner(state_repo=repo, event_bus=_Bus()), repo


class _Bus:
    async def publish(self, *a, **k):
        return None


async def _finish(runner, release):
    release.set()
    for task in list(runner._tasks.values()):
        await asyncio.wait_for(task, timeout=5)


async def test_two_concurrent_answers_start_one_flow():
    runner, _ = await _runner(SessionStatus.WAITING)
    release, built = asyncio.Event(), []

    def factory(_s):
        built.append(1)
        return _Flow(release)

    results = await asyncio.gather(
        runner.resume_session("s1", "yes", factory),
        runner.resume_session("s1", "yes", factory),
        return_exceptions=True,
    )
    await _finish(runner, release)
    assert len(built) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1


async def test_two_concurrent_starts_of_one_pending_session_start_one_flow():
    runner, repo = await _runner(SessionStatus.PENDING)
    session = await repo.load_session("s1")
    release, built = asyncio.Event(), []

    def factory(_s):
        built.append(1)
        return _Flow(release)

    results = await asyncio.gather(
        runner.start_session(session, factory),
        runner.start_session(session, factory),
        return_exceptions=True,
    )
    await _finish(runner, release)
    assert len(built) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1


async def test_a_second_start_after_the_first_finished_is_allowed():
    runner, repo = await _runner(SessionStatus.PENDING)
    release, built = asyncio.Event(), []
    release.set()

    def factory(_s):
        built.append(1)
        return _Flow(release)

    await runner.start_session(await repo.load_session("s1"), factory)
    await _finish(runner, release)
    await runner.start_session(await repo.load_session("s1"), factory)
    await _finish(runner, release)
    assert len(built) == 2


def test_idle_session_locks_do_not_accumulate():
    runner = TaskRunner(state_repo=_SlowRepo(), event_bus=_Bus())
    for i in range(50):
        runner._lock_for(f"s{i}")
    import gc

    gc.collect()
    assert len(runner._session_locks) == 0


@pytest.fixture(autouse=True)
def _quiet_presence(monkeypatch):
    monkeypatch.setattr(TaskRunner, "_publish_presence", lambda self, session: _noop())


async def _noop():
    return None
