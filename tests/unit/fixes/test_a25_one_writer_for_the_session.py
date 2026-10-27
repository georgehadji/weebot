"""A25 repro (strict xfail until fixed): TaskRunner and the flow's EventPublisher both save the
whole session, from different copies. An event the flow emitted and saved but did not yield
exists only in the flow's copy, so the runner's save over it drops that event."""

from __future__ import annotations

import pytest

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
        self._repo = repo
        self._session = session

    async def run(self, prompt: str):
        emitted = MessageEvent(role="assistant", message="emitted, never yielded")
        self._session = self._session.add_event(emitted)
        await self._repo.save_session(self._session)
        yield DoneEvent()

    def is_done(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass


@pytest.mark.xfail(strict=True, reason="A25: two writers save the whole session")
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
