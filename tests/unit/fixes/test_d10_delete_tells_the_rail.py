"""D10 (UI defect hunt W5, 2026-10-31): a deleted session stayed in the session rail.

The rail updates only from presence frames, and deleting a session sent none, so the row
stayed until a reload. The delete route now publishes a presence frame with status
"deleted"; the UI drops that row (weebot-ui/src/hooks/useSessionList.ts).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.services.session_deletion_orchestrator import (
    SessionDeletionOrchestrator,
)
from weebot.domain.models.event import SessionPresenceEvent
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


@pytest.mark.asyncio
async def test_deleting_a_session_publishes_a_deleted_presence_frame():
    from weebot.interfaces.web.routers import sessions as router

    repo = InMemoryStateRepository()
    await repo.save_session(Session(id="s3", user_id="alice"))
    bus = SimpleNamespace(publish=AsyncMock())
    ports = {EventBusPort: bus}

    def _get(key):
        if key in ports:
            return ports[key]
        raise KeyError(key)

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        container=SimpleNamespace(get=_get))))
    with patch.object(router, "verify_session_ownership", AsyncMock()), \
         patch.object(router, "build_deletion_orchestrator",
                      lambda _req, repo_: SessionDeletionOrchestrator(state_repo=repo_)):
        await router.delete_session("s3", http_request=request, state_repo=repo, _mutation=None)

    frames = [c.args[0] for c in bus.publish.await_args_list]
    assert any(
        isinstance(f, SessionPresenceEvent) and f.about_session_id == "s3"
        and f.status == "deleted" for f in frames
    ), frames
