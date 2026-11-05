"""H21: rewind, retry and branch a conversation. Tests the timeline cuts and the use case."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from weebot.application.use_cases.rewind_session import (
    JOURNAL_EVENT,
    RewindSession,
    SessionBusy,
)
from weebot.domain.models.event import MessageEvent, ToolEvent
from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.models.workspace_checkpoint import CheckpointRef, RestoreReport
from weebot.domain.services.session_timeline import cut_at, cut_back, turn_boundaries
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _conversation() -> Session:
    """Two turns: user, tool, assistant, user, tool, assistant."""
    events = [
        MessageEvent(role="user", message="first", timestamp=_at(0)),
        ToolEvent(tool_name="bash", timestamp=_at(1)),
        MessageEvent(role="assistant", message="done one", timestamp=_at(2)),
        MessageEvent(role="user", message="second", timestamp=_at(10)),
        ToolEvent(tool_name="file_editor", timestamp=_at(11)),
        MessageEvent(role="assistant", message="done two", timestamp=_at(12)),
    ]
    return Session(
        id="s1", user_id="u", status=SessionStatus.COMPLETED, title="chat", events=events
    )


class FakeCheckpoints:
    def __init__(self, refs: list[CheckpointRef]) -> None:
        self.refs = refs
        self.restored: list[CheckpointRef] = []

    async def list(self, session_id, limit=50):
        return list(self.refs)

    async def restore(self, ref, *, paths=()):
        self.restored.append(ref)
        return RestoreReport(restored=("a.py", "b.py"))


class FakeJournal:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict]] = []

    async def log_event(self, session_id, event_type, data, **_):
        self.rows.append((session_id, event_type, data))


def _ref(ident: str, seconds: int) -> CheckpointRef:
    return CheckpointRef(
        id=ident, session_id="s1", turn_id="step", tree_sha="x", root="/w",
        created_at=_at(seconds), file_count=1,
    )


async def _repo(session: Session) -> InMemoryStateRepository:
    repo = InMemoryStateRepository()
    await repo.save_session(session)
    return repo


def test_the_timeline_cuts_at_user_messages():
    events = _conversation().events

    assert [b.text for b in turn_boundaries(events)] == ["first", "second"]
    kept, dropped, boundary = cut_back(events, 1)
    assert len(kept) == 3 and len(dropped) == 3 and boundary.text == "second"
    with pytest.raises(ValueError):
        cut_back(events, 3)
    kept, dropped = cut_at(events, events[1].id)
    assert len(kept) == 2 and len(dropped) == 4


@pytest.mark.asyncio
async def test_rewinding_a_turn_removes_its_events_and_restores_the_files_it_changed():
    session = _conversation()
    repo = await _repo(session)
    checkpoints = FakeCheckpoints([_ref("before-turn-1", 1), _ref("before-turn-2", 11)])

    result = await RewindSession(repo, FakeJournal(), checkpoints).rewind("s1", turns=1)

    saved = await repo.load_session("s1")
    assert [e.id for e in saved.events] == [e.id for e in session.events[:3]]
    assert result.dropped == 3 and result.dropped_text == "second"
    assert [r.id for r in checkpoints.restored] == ["before-turn-2"]
    assert result.files_changed == 2


@pytest.mark.asyncio
async def test_the_journal_still_holds_the_dropped_events():
    session = _conversation()
    repo = await _repo(session)
    journal = FakeJournal()

    await RewindSession(repo, journal).rewind("s1", turns=1, files=False)

    ((_, kind, data),) = journal.rows
    assert kind == JOURNAL_EVENT
    assert data["dropped_ids"] == [e.id for e in session.events[3:]]


@pytest.mark.asyncio
async def test_a_rewind_without_files_leaves_the_workspace_alone():
    repo = await _repo(_conversation())
    checkpoints = FakeCheckpoints([_ref("c", 11)])

    await RewindSession(repo, None, checkpoints).rewind("s1", turns=1, files=False)

    assert checkpoints.restored == []


@pytest.mark.asyncio
async def test_a_branch_shares_no_mutable_state_with_the_original():
    session = _conversation()
    repo = await _repo(session)

    child = await RewindSession(repo).branch("s1", session.events[2].id)

    assert child.id != "s1" and len(child.events) == 3
    assert child.context.extra["parent_session_id"] == "s1"
    assert child.context.extra["branched_from_event"] == session.events[2].id
    child.events[0].message = "changed in the branch"
    child.context.extra["note"] = "branch only"
    original = await repo.load_session("s1")
    assert original.events[0].message == "first"
    assert "note" not in original.context.extra
    assert len(original.events) == 6


@pytest.mark.asyncio
async def test_rewinding_during_a_run_is_refused():
    session = _conversation().set_status(SessionStatus.RUNNING)
    repo = await _repo(session)

    with pytest.raises(SessionBusy):
        await RewindSession(repo).rewind("s1")
    with pytest.raises(SessionBusy):
        await RewindSession(repo).branch("s1", session.events[0].id)
    assert len((await repo.load_session("s1")).events) == 6


@pytest.mark.asyncio
async def test_the_rewind_route_answers_409_while_a_run_is_active():
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from weebot.interfaces.web.routers import sessions as router

    repo = await _repo(_conversation().set_status(SessionStatus.RUNNING))
    with patch.object(router, "verify_session_ownership", AsyncMock()):
        with pytest.raises(HTTPException) as raised:
            await router.rewind_session(
                "s1", MagicMock(), router.RewindSessionRequest(), state_repo=repo, _mutation=None
            )
    assert raised.value.status_code == 409


@pytest.mark.asyncio
async def test_the_retry_route_rewinds_one_turn_and_resends_that_message():
    from unittest.mock import AsyncMock, MagicMock, patch

    from weebot.interfaces.web.routers import sessions as router

    repo = await _repo(_conversation())
    dispatch = AsyncMock(return_value=MagicMock(session="after"))
    with patch.object(router, "verify_session_ownership", AsyncMock()), \
         patch.object(router, "_dispatch_input", dispatch), \
         patch.object(router, "_respond", AsyncMock(return_value="ok")), \
         patch.object(router, "_rewinder", lambda req, repo_: RewindSession(repo_)):
        out = await router.retry_session("s1", MagicMock(), state_repo=repo, _mutation=None)

    assert out == "ok"
    assert dispatch.await_args.args[2] == "second"
    assert len((await repo.load_session("s1")).events) == 3
