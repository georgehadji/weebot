"""A25: TaskRunner and the flow's EventPublisher both saved the whole session, from different
copies. An event the flow emitted and saved but did not yield exists only in the flow's copy,
so the runner's save over it dropped that event. The flow now owns persistence; the runner
writes once, at the end, from the flow's copy plus what only it saw."""

from __future__ import annotations

from weebot.application.services.task_runner import TaskRunner
from weebot.domain.models.event import DoneEvent, MessageEvent
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


class _Bus:
    async def publish(self, *a, **k):
        return None


class _EmittingFlow:
    """Saves an event itself (as EventPublisher does) and yields a different one."""

    def __init__(self, repo, session: Session) -> None:
        self._state_repo = repo
        self._session = session

    async def run(self, prompt: str):
        emitted = MessageEvent(role="assistant", message="emitted, never yielded")
        self._session = self._session.add_event(emitted)
        await self._state_repo.save_session(self._session)
        yield DoneEvent()

    def is_done(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass


async def test_an_event_the_flow_saved_survives_the_run():
    repo = InMemoryStateRepository()
    session = Session(
        id="s1", user_id="u", agent_id="a", status=SessionStatus.RUNNING,
        context={"last_prompt": "task"},
    )
    await repo.save_session(session)
    flow = _EmittingFlow(repo, session)
    runner = TaskRunner(state_repo=repo, event_bus=_Bus())

    await runner._run_flow_logged("s1", flow, "task")

    final = await repo.load_session("s1")
    texts = [getattr(e, "message", "") for e in final.events]
    assert "emitted, never yielded" in texts


async def test_an_event_only_the_runner_saw_is_kept_too():
    repo = InMemoryStateRepository()
    session = Session(
        id="s1", user_id="u", agent_id="a", status=SessionStatus.RUNNING,
        context={"last_prompt": "task"},
    )
    await repo.save_session(session)
    flow = _EmittingFlow(repo, session)
    runner = TaskRunner(state_repo=repo, event_bus=_Bus())

    await runner._run_flow_logged("s1", flow, "task")

    final = await repo.load_session("s1")
    assert [e.type for e in final.events].count("done") == 1


async def test_a_flow_that_does_not_own_persistence_is_still_saved_by_the_runner():
    class _Plain(_EmittingFlow):
        def __init__(self, session):
            self._session = session

        async def run(self, prompt):
            yield MessageEvent(role="assistant", message="only yielded")
            yield DoneEvent()

    repo = InMemoryStateRepository()
    session = Session(id="s2", user_id="u", agent_id="a", status=SessionStatus.RUNNING)
    await repo.save_session(session)
    flow = _Plain(session)
    del flow._session  # no session of its own, no repo: the runner is the only writer
    runner = TaskRunner(state_repo=repo, event_bus=_Bus())

    await runner._run_flow_logged("s2", flow, "task")

    final = await repo.load_session("s2")
    assert [getattr(e, "message", "") for e in final.events][:1] == ["only yielded"]
