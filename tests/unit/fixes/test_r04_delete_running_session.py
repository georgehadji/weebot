"""R04 (audit 2026-10-29): deleting a running session stops it first.

DELETE /sessions/{id} ran the deletion cascade while the session's flow kept running; the
flow's next save is an upsert, so the session came back (and kept running) after the user
was told it was deleted. The DeleteSession use case cancels the run, then deletes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from weebot.application.services.session_deletion_orchestrator import (
    SessionDeletionOrchestrator,
)
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


class _Runner:
    """A TaskRunner whose flow saves the session again a moment later."""

    def __init__(self, repo, session):
        self.task = asyncio.create_task(self._flow(repo, session))

    @staticmethod
    async def _flow(repo, session):
        await asyncio.sleep(0.05)
        await repo.save_session(session)  # the flow's next checkpoint

    async def cancel_session(self, session_id: str) -> bool:
        if self.task.done():
            return False
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        return True


@pytest.mark.asyncio
async def test_the_use_case_stops_the_run_before_deleting():
    from weebot.application.use_cases.delete_session import DeleteSession

    repo = InMemoryStateRepository()
    session = Session(id="s1", user_id="alice")
    await repo.save_session(session)
    runner = _Runner(repo, session)

    await DeleteSession(runner, SessionDeletionOrchestrator(state_repo=repo)).execute("s1")
    await asyncio.sleep(0.1)
    assert await repo.load_session("s1") is None, "the running flow brought the session back"
    assert runner.task.cancelled()


@pytest.mark.asyncio
async def test_the_route_uses_it():
    from weebot.interfaces.web.routers import sessions as router

    repo = InMemoryStateRepository()
    session = Session(id="s2", user_id="alice")
    await repo.save_session(session)
    runner = _Runner(repo, session)
    container = SimpleNamespace(get=lambda key: runner)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))

    with patch.object(router, "verify_session_ownership", AsyncMock()), \
         patch.object(router, "build_deletion_orchestrator",
                      lambda _req, repo_: SessionDeletionOrchestrator(state_repo=repo_)):
        await router.delete_session("s2", http_request=request, state_repo=repo, _mutation=None)
    await asyncio.sleep(0.1)
    assert await repo.load_session("s2") is None
