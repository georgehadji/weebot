"""SCL-1 input (plan Phase 8): retry budget and dead letter live on the Session.

`TaskRunner` used to keep the retry count and the dead-letter list in process dicts, so
a restart handed every failed session a fresh budget and emptied the dead-letter queue.
Both are now the persisted Session (`context.extra`), and a second runner sees them.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services import task_runner as task_runner_module
from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.session import Session, SessionStatus


class MemoryRepo(StateRepositoryPort):
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    async def save_session(self, session):
        self.sessions[session.id] = session

    async def load_session(self, session_id):
        return self.sessions.get(session_id)

    async def list_sessions(self, user_id=None, status=None, limit=100, offset=0):
        return [s for s in self.sessions.values() if status is None or s.status.value == status]

    async def count_sessions(self, user_id=None):  # pragma: no cover
        return len(self.sessions)

    async def update_session_status(self, session_id, status):  # pragma: no cover
        pass

    async def delete_session(self, session_id):  # pragma: no cover
        pass

    async def search_sessions(self, query, limit=20):  # pragma: no cover
        return []

    async def get_low_salience_entries(self, threshold=0.3, limit=50):  # pragma: no cover
        return []


class ExplodingFlow:
    def __init__(self, session):
        self._session = session

    async def run(self, prompt):
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover - makes this an async generator

    def is_done(self):  # pragma: no cover
        return False

    async def teardown(self):
        return None


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(task_runner_module.asyncio, "sleep", instant)


async def _settle(runner: TaskRunner, sid: str) -> None:
    """Wait for the session's current task, and any retry task it started, to finish."""
    for _ in range(20):
        task = runner._tasks.get(sid)
        if task is None or task.done():
            await asyncio.sleep(0)
            if runner._tasks.get(sid) is None or runner._tasks[sid].done():
                return
        else:
            await asyncio.wait({task}, timeout=10)


async def _run_to_failure(runner: TaskRunner, repo: MemoryRepo, sid: str) -> list[ExplodingFlow]:
    flows: list[ExplodingFlow] = []

    def factory(session):
        flows.append(ExplodingFlow(session))
        return flows[-1]

    session = Session(id=sid, user_id="u", agent_id="a")
    await repo.save_session(session)
    await runner.start_session(session, factory)
    await _settle(runner, sid)
    return flows


@pytest.mark.asyncio
async def test_an_exhausted_session_is_failed_with_its_reason_on_the_session():
    repo = MemoryRepo()
    runner = TaskRunner(state_repo=repo, max_session_retries=2)
    flows = await _run_to_failure(runner, repo, "dead-1")

    assert len(flows) == 3, "the first run plus two retries"
    saved = repo.sessions["dead-1"]
    assert saved.status is SessionStatus.FAILED
    assert saved.context.extra["retries_remaining"] == 0
    assert "provider exploded" in saved.context.extra["failure_reason"]


@pytest.mark.asyncio
async def test_the_dead_letter_list_survives_a_restart():
    repo = MemoryRepo()
    await _run_to_failure(TaskRunner(state_repo=repo, max_session_retries=1), repo, "dead-2")

    after_restart = TaskRunner(state_repo=repo, max_session_retries=1)  # a new process
    failed = await after_restart.list_failed_sessions()
    assert list(failed) == ["dead-2"] and "provider exploded" in failed["dead-2"]


@pytest.mark.asyncio
async def test_a_restart_does_not_hand_back_a_spent_budget():
    repo = MemoryRepo()
    spent = Session(id="spent", user_id="u", agent_id="a")
    spent = spent.model_copy(
        update={"context": spent.context.model_copy(update={"extra": {"retries_remaining": 0}})}
    )
    await repo.save_session(spent)

    runner = TaskRunner(state_repo=repo, max_session_retries=3)
    flows: list[ExplodingFlow] = []

    def factory(session):
        flows.append(ExplodingFlow(session))
        return flows[-1]

    await runner.start_session(spent, factory)
    await _settle(runner, "spent")
    assert len(flows) == 1, "no retry: the budget was already spent before the restart"


@pytest.mark.asyncio
async def test_a_rerun_clears_the_failure_reason():
    repo = MemoryRepo()
    runner = TaskRunner(state_repo=repo, max_session_retries=1)
    await _run_to_failure(runner, repo, "rerun")
    assert await runner.rerun_failed_session("rerun", lambda s: ExplodingFlow(s)) is True
    assert "failure_reason" not in repo.sessions["rerun"].context.extra
