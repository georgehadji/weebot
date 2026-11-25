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


async def test_resume_while_the_paused_task_still_drains_is_refused(monkeypatch):
    """WAITING is saved before the paused flow's task ends; an answer in that window must not
    start a second flow (audit X1), nor be stored."""
    monkeypatch.setattr("weebot.application.services.task_runner._RESUME_DRAIN_WAIT_S", 0.05)
    runner, repo = await _runner(SessionStatus.PENDING)
    release, built = asyncio.Event(), []

    def factory(_s):
        built.append(1)
        return _Flow(release)

    await runner.start_session(await repo.load_session("s1"), factory)
    waiting = (await repo.load_session("s1")).set_status(SessionStatus.WAITING)
    await repo.save_session(waiting)  # the flow paused; its task is still alive

    with pytest.raises(ValueError, match="still running"):
        await runner.resume_session("s1", "yes", factory)
    stored = await repo.load_session("s1")
    assert stored.status == SessionStatus.WAITING
    assert not any(getattr(e, "message", None) == "yes" for e in stored.events)
    await _finish(runner, release)
    assert len(built) == 1


async def test_resume_waits_for_the_drain_to_end():
    runner, repo = await _runner(SessionStatus.PENDING)
    release, built = asyncio.Event(), []

    def factory(_s):
        built.append(1)
        return _Flow(release)

    await runner.start_session(await repo.load_session("s1"), factory)
    await repo.save_session((await repo.load_session("s1")).set_status(SessionStatus.WAITING))
    asyncio.get_running_loop().call_later(0.05, release.set)

    await runner.resume_session("s1", "yes", factory)
    await _finish(runner, release)
    assert len(built) == 2


async def test_cancel_waits_for_the_session_lock():
    runner, _ = await _runner(SessionStatus.WAITING)
    async with runner._lock_for("s1"):
        cancel = asyncio.ensure_future(runner.cancel_session("s1"))
        await asyncio.sleep(0.01)
        assert not cancel.done()
    assert await cancel is False


async def test_cancel_stops_a_live_task_and_marks_cancelled():
    runner, repo = await _runner(SessionStatus.PENDING)
    release = asyncio.Event()
    await runner.start_session(await repo.load_session("s1"), lambda _s: _Flow(release))

    assert await asyncio.wait_for(runner.cancel_session("s1"), timeout=5) is True
    assert (await repo.load_session("s1")).status == SessionStatus.CANCELLED


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (SessionStatus.WAITING, SessionStatus.CANCELLED),
        (SessionStatus.PENDING, SessionStatus.CANCELLED),
        (SessionStatus.COMPLETED, SessionStatus.COMPLETED),
        (SessionStatus.FAILED, SessionStatus.FAILED),
    ],
)
async def test_cancel_with_no_live_task_writes_status_only_and_only_if_allowed(status, expected):
    runner, repo = await _runner(status)
    saves = []
    original = repo.save_session

    async def spy(session):
        saves.append(session)
        await original(session)

    repo.save_session = spy
    assert await runner.cancel_session("s1") is False
    assert (await repo.load_session("s1")).status == expected
    assert saves == []


async def test_rerun_failed_session_refuses_while_a_flow_runs():
    runner, repo = await _runner(SessionStatus.PENDING)
    release, built = asyncio.Event(), []

    def factory(_s):
        built.append(1)
        return _Flow(release)

    await runner.start_session(await repo.load_session("s1"), factory)
    await repo.save_session((await repo.load_session("s1")).set_status(SessionStatus.FAILED))

    assert await runner.rerun_failed_session("s1", factory) is False
    await _finish(runner, release)
    assert len(built) == 1


async def test_a_queued_session_already_running_is_skipped():
    runner, repo = await _runner(SessionStatus.PENDING)
    release, built = asyncio.Event(), []

    def factory(_s):
        built.append(1)
        return _Flow(release)

    session = await repo.load_session("s1")
    await runner.start_session(session, factory)
    await runner._start_queued(session, factory)
    await _finish(runner, release)
    assert len(built) == 1


async def test_a_session_cancelled_while_queued_is_not_started():
    runner, repo = await _runner(SessionStatus.PENDING)
    built = []
    queued = await repo.load_session("s1")
    await runner.cancel_session("s1")  # status-only write: CANCELLED
    await runner._start_queued(queued, lambda _s: built.append(1))
    assert built == []
    assert (await repo.load_session("s1")).status == SessionStatus.CANCELLED


async def test_a_failed_session_queued_on_purpose_for_a_rerun_is_started():
    runner, repo = await _runner(SessionStatus.FAILED)
    release, built = asyncio.Event(), []
    release.set()

    def factory(_s):
        built.append(1)
        return _Flow(release)

    snapshot = (await repo.load_session("s1")).model_copy(
        update={"status": SessionStatus.PENDING}
    )
    await runner._start_queued(snapshot, factory)  # stored FAILED, queued as PENDING
    await _finish(runner, release)
    assert built == [1]


async def test_a_queued_start_survives_a_failed_reload():
    runner, repo = await _runner(SessionStatus.PENDING)
    release, built = asyncio.Event(), []
    release.set()
    queued = await repo.load_session("s1")

    real_load, failures = repo.load_session, []

    async def flaky_load(session_id):
        if not failures:  # only the worker's reload fails; the flow's own load works
            failures.append(1)
            raise OSError("db gone")
        return await real_load(session_id)

    repo.load_session = flaky_load

    def factory(_s):
        built.append(1)
        return _Flow(release)

    await runner._start_queued(queued, factory)
    await _finish(runner, release)
    assert built == [1]


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
