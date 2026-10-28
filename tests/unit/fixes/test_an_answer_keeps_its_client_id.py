"""An answer the UI showed optimistically is stored under the UI's id, so it shows once.

Found on live session de5d0990: the clarifying answer and "approved" each appeared twice
in the timeline. The UI adds the message at once with its own id and settles it when
the server echoes that id; the server stored the answer under a new uuid, so the echo
became a second row and the optimistic one never settled.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from weebot.application.services.task_runner import TaskRunner
from weebot.application.use_cases.dispatch_session_input import (
    SessionInputContext,
    dispatch_session_input,
)
from weebot.domain.models.event import DoneEvent, MessageEvent
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository
from weebot.interfaces.web.schemas.requests import SessionInputRequest

CLIENT_ID = "6f1c2a9e-3b7d-4c55-9a10-2e8f4b7c1d03"


class _Flow:
    async def run(self, prompt):
        yield DoneEvent()

    def is_done(self):
        return True

    async def teardown(self):
        pass


class _Bus:
    async def publish(self, *a, **k):
        return None


async def test_the_stored_answer_carries_the_client_id():
    repo = InMemoryStateRepository()
    await repo.save_session(Session(id="s1", status=SessionStatus.WAITING))
    runner = TaskRunner(state_repo=repo, event_bus=_Bus())

    session = await runner.resume_session("s1", "approved", lambda s: _Flow(), message_id=CLIENT_ID)
    answers = [e for e in session.events if isinstance(e, MessageEvent) and e.role == "user"]
    assert [e.id for e in answers] == [CLIENT_ID]


async def test_a_reused_id_gets_a_fresh_one():
    session = Session(id="s1").add_user_message("first", message_id=CLIENT_ID)
    session = session.add_user_message("second", message_id=CLIENT_ID)
    ids = [e.id for e in session.events]
    assert ids[0] == CLIENT_ID and ids[1] != CLIENT_ID


async def test_dispatch_passes_the_client_id_to_resume():
    runner = MagicMock()
    runner.create_plan_act_factory = MagicMock(return_value=lambda s: MagicMock())
    runner.resume_session = AsyncMock(return_value=Session(id="s1"))
    tools = MagicMock(teardown=AsyncMock())
    ctx = SessionInputContext(
        session=Session(id="s1", status=SessionStatus.WAITING),
        text="approved",
        client_msg_id=CLIENT_ID,
        state_repo=AsyncMock(),
        task_runner=runner,
        llm=MagicMock(),
        event_bus=MagicMock(),
        steering=AsyncMock(),
        build_tools=AsyncMock(return_value=tools),
        build_chat_flow=lambda s, m: MagicMock(),
    )
    await dispatch_session_input(ctx)
    assert runner.resume_session.await_args.kwargs["message_id"] == CLIENT_ID


def test_the_request_accepts_only_id_shaped_values():
    assert SessionInputRequest(text="x", client_msg_id=CLIENT_ID).client_msg_id == CLIENT_ID
    with pytest.raises(ValidationError):
        SessionInputRequest(text="x", client_msg_id="x" * 200)
    with pytest.raises(ValidationError):
        SessionInputRequest(text="x", client_msg_id="<script>")
