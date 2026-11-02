"""A session left RUNNING by a process that stopped must not stay RUNNING for good.

The run is an asyncio task inside the server process. When that process is killed or crashes,
the database still says RUNNING, nothing runs the session, and a message sent from the composer
is steered into a flow that does not exist (seen live: "still working?" got no answer).
`interrupt_orphans` runs at startup and marks such sessions FAILED with a reason, so they appear
in the dead-letter list and the composer's FAILED path resumes them at the first unfinished step.
"""

from __future__ import annotations

import asyncio

from weebot.application.ports.task_runner_port import TaskRunnerPort
from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.event import PlanEvent, PlanStatus
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


async def _repo_with(*sessions: Session) -> InMemoryStateRepository:
    repo = InMemoryStateRepository()
    for s in sessions:
        await repo.save_session(s)
    return repo


def _session(sid: str, status: SessionStatus) -> Session:
    return Session(id=sid, user_id="u", agent_id="a", status=status)


async def test_a_running_session_nothing_runs_is_marked_failed_with_a_reason():
    repo = await _repo_with(_session("s1", SessionStatus.RUNNING))
    runner = TaskRunner(state_repo=repo)

    assert await runner.interrupt_orphans() == ["s1"]

    session = await repo.load_session("s1")
    assert session.status is SessionStatus.FAILED
    assert "interrupted" in (await runner.list_failed_sessions())["s1"]


async def test_the_saved_plan_and_events_survive_the_mark():
    plan = Plan(title="p", message="m", steps=[Step(id="a", description="x", status="completed")])
    session = _session("s1", SessionStatus.RUNNING).add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump())
    )
    repo = await _repo_with(session)

    await TaskRunner(state_repo=repo).interrupt_orphans()

    recovered = await repo.load_session("s1")
    assert recovered.get_last_plan() is not None
    assert len(recovered.events) == len(session.events)


async def test_a_session_this_runner_is_running_is_left_alone():
    repo = await _repo_with(_session("live", SessionStatus.RUNNING))
    runner = TaskRunner(state_repo=repo)
    task = asyncio.create_task(asyncio.sleep(30))
    runner._tasks["live"] = task
    try:
        assert await runner.interrupt_orphans() == []
        assert (await repo.load_session("live")).status is SessionStatus.RUNNING
    finally:
        task.cancel()


async def test_other_statuses_are_untouched():
    others = [
        _session("p", SessionStatus.PENDING),
        _session("w", SessionStatus.WAITING),
        _session("c", SessionStatus.COMPLETED),
        _session("f", SessionStatus.FAILED),
    ]
    repo = await _repo_with(*others)
    assert await TaskRunner(state_repo=repo).interrupt_orphans() == []
    for s in others:
        assert (await repo.load_session(s.id)).status is s.status


async def test_it_is_idempotent():
    repo = await _repo_with(_session("s1", SessionStatus.RUNNING))
    runner = TaskRunner(state_repo=repo)
    await runner.interrupt_orphans()
    assert await runner.interrupt_orphans() == []


async def test_more_orphans_than_one_page_are_all_marked():
    repo = await _repo_with(*(_session(f"s{i}", SessionStatus.RUNNING) for i in range(130)))
    marked = await TaskRunner(state_repo=repo).interrupt_orphans()
    assert len(marked) == 130
    assert not await repo.list_sessions(status="running", limit=500)


def test_the_interfaces_layer_may_call_it_through_the_port():
    assert hasattr(TaskRunnerPort, "interrupt_orphans")
