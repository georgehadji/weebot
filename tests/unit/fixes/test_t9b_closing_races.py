"""Races left around a run's start, pause and end (review of PR 194, T4-T9).

A cancel filed before the flow started was dropped; the cancel marker could be read half
written; a resume saved a copy it had loaded before waiting for the paused task; a cancel
between the run's last read and its closing save was overwritten; a failed save counted as
saved; a factory error in the queue was reported as "already running".
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from weebot.application.services.task_runner import TaskRunner, _with_extra
from weebot.core import cancel_requests
from weebot.domain.models.event import DoneEvent, MessageEvent, WaitForUserEvent
from weebot.domain.models.session import Session, SessionAction, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


class _Bus:
    async def publish(self, *a, **k):
        return None


class _Flow:
    def __init__(self, release: asyncio.Event | None = None, session=None) -> None:
        self._release = release
        if session is not None:  # a flow that saves its own session
            self._session, self._state_repo = session, object()

    async def run(self, prompt: str):
        if self._release is not None:
            await self._release.wait()
        yield DoneEvent()

    def is_done(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass


async def _runner(repo, status=SessionStatus.PENDING):
    await repo.save_session(
        Session(id="s1", user_id="u", agent_id="a", status=status, context={"last_prompt": "t"})
    )
    return TaskRunner(state_repo=repo, event_bus=_Bus())


async def _finish(runner):
    for task in list(runner._tasks.values()):
        await asyncio.wait_for(task, timeout=5)


# ── cancel marker ────────────────────────────────────────────────────────────


def test_the_marker_is_never_written_in_place(tmp_path, monkeypatch):
    """take() reads the marker every iteration: a write that truncates it first can be read empty."""
    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    marker = cancel_requests._marker("s1")
    written: list[Path] = []
    real = Path.write_text

    def spy(self, *a, **k):
        written.append(self)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", spy)
    cancel_requests.request("s1")
    assert marker not in written
    assert cancel_requests.take("s1")
    assert list(tmp_path.iterdir()) == []  # no temp file left behind


async def test_a_cancel_filed_after_the_run_was_scheduled_is_seen(tmp_path, monkeypatch):
    """The runner saved RUNNING, then the flow waited for a slot; a cancel filed meanwhile
    is for this run, though it predates the flow's own start."""
    from weebot.application.flows.plan_act_flow import PlanActFlow
    from weebot.application.models.tool_collection import ToolCollection

    monkeypatch.setattr(cancel_requests, "_DIR", tmp_path)
    scheduled = datetime.now(UTC) - timedelta(seconds=10)
    session = Session(id="run-3", task="t", status=SessionStatus.RUNNING, updated_at=scheduled)
    flow = PlanActFlow(llm=MagicMock(), tools=ToolCollection(), session=session)
    real = time.time
    with monkeypatch.context() as m:
        m.setattr(time, "time", lambda: real() - 5)  # after `scheduled`, before the flow starts
        cancel_requests.request("run-3")
    [e async for e in flow.run("do it")]
    assert flow._session.status == SessionStatus.CANCELLED


# ── resume ───────────────────────────────────────────────────────────────────


async def test_resume_builds_on_the_row_the_old_run_saved_while_draining():
    repo = InMemoryStateRepository()
    runner = await _runner(repo)
    release, seen = asyncio.Event(), []

    def factory(s):
        seen.append(s.context.extra.get("kept"))
        return _Flow(release, _with_extra(s, kept="by the old run"))

    await runner.start_session(await repo.load_session("s1"), factory)
    await repo.save_session((await repo.load_session("s1")).set_status(SessionStatus.WAITING))
    asyncio.get_running_loop().call_later(0.05, release.set)

    await runner.resume_session("s1", "yes", factory)
    await _finish(runner)
    assert seen[1] == "by the old run"  # the old run's closing save was not overwritten


# ── closing save ─────────────────────────────────────────────────────────────


class _CancelBeforeTheSave(InMemoryStateRepository):
    """A cancel lands between the runner's read and its closing write."""

    fired = False

    async def save_session_if_unchanged(self, session, expected_updated_at):
        if not self.fired:
            self.fired = True
            await asyncio.sleep(0.05)  # the clock ticks about every 15 ms on Windows
            await self.update_session_status(
                session.id,
                SessionStatus.CANCELLED,
                expected=SessionStatus.allowing(SessionAction.CANCEL),
            )
        return await super().save_session_if_unchanged(session, expected_updated_at)


async def test_a_cancel_between_the_last_read_and_the_closing_save_is_kept():
    repo = _CancelBeforeTheSave()
    runner = await _runner(repo)
    await runner.start_session(await repo.load_session("s1"), lambda _s: _Flow())
    await _finish(runner)
    assert repo.fired
    assert (await repo.load_session("s1")).status == SessionStatus.CANCELLED


# ── queue ────────────────────────────────────────────────────────────────────


async def test_a_factory_error_in_the_queue_fails_the_session_instead_of_hiding_it():
    repo = InMemoryStateRepository()
    runner = await _runner(repo)

    def factory(_s):
        raise ValueError("bad config")

    await runner._start_queued(await repo.load_session("s1"), factory)
    assert (await repo.load_session("s1")).status == SessionStatus.FAILED


# ── publisher ────────────────────────────────────────────────────────────────


class _FlakyRepo(InMemoryStateRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True
        self.saves = 0

    async def save_session(self, session):
        self.saves += 1
        if self.fail:
            raise OSError("disk")
        await super().save_session(session)


def _publisher(repo, status=SessionStatus.RUNNING):
    from weebot.application.flows.event_publisher import EventPublisher

    session = Session(id="p1", user_id="u", agent_id="a", status=status)
    return EventPublisher(session=session, state_repo=repo, event_bus=None)


async def test_a_failed_save_is_retried_with_the_next_event():
    repo = _FlakyRepo()
    pub = _publisher(repo)
    await pub.emit(MessageEvent(role="assistant", message="one"))
    assert repo.saves == 1  # failed, logged
    repo.fail = False
    await pub.emit(MessageEvent(role="assistant", message="two"))
    assert repo.saves == 2  # not skipped as "already saved"
    assert len((await repo.load_session("p1")).events) == 2


async def test_a_question_nobody_waits_on_does_not_abort_the_run_on_a_save_error():
    pub = _publisher(_FlakyRepo(), status=SessionStatus.RUNNING)  # AUTO mode: never WAITING
    await pub.emit(WaitForUserEvent(question="ok?"))  # logged, not raised


async def test_a_real_pause_still_stops_on_a_save_error():
    pub = _publisher(_FlakyRepo(), status=SessionStatus.WAITING)
    with pytest.raises(OSError):
        await pub.emit(WaitForUserEvent(question="ok?"))
