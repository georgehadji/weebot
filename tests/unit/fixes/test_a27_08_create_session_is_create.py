"""A08: POST /api/sessions with an existing session_id must not overwrite that session."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


async def test_create_session_inserts_once():
    repo = InMemoryStateRepository()
    assert await repo.create_session(Session(id="s1", user_id="alice")) is True
    assert await repo.create_session(Session(id="s1", user_id="mallory")) is False
    assert (await repo.load_session("s1")).user_id == "alice"


async def test_sqlite_create_session_inserts_once(tmp_path):
    from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    first = Session(id="s1", user_id="alice")
    results = [await repo.create_session(first), await repo.create_session(Session(id="s1"))]
    assert results == [True, False]
    assert (await repo.load_session("s1")).user_id == "alice"


async def test_route_answers_409_for_an_existing_id():
    from weebot.interfaces.web.routers import sessions as router

    repo = InMemoryStateRepository()
    await repo.save_session(Session(id="taken", user_id="alice", context={"last_prompt": "keep"}))
    body = router.CreateSessionRequest(prompt="hijack", session_id="taken")
    with patch.object(router, "get_current_user_id", return_value="mallory"), \
         patch.object(router, "_respond", AsyncMock()):
        with pytest.raises(HTTPException) as raised:
            await router.create_session(
                http_request=MagicMock(), body=body, state_repo=repo, _mutation=None
            )
    assert raised.value.status_code == 409
    kept = await repo.load_session("taken")
    assert kept.user_id == "alice" and kept.context["last_prompt"] == "keep"
