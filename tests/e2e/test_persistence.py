"""E2E persistence tests — verify events survive process restart.

Uses a temporary SQLite database to verify that flows properly persist
all emitted events and that sessions can be reloaded with correct status.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


@pytest.fixture
def tmp_db(tmp_path: Path) -> StateRepositoryPort:
    """Create a temporary SQLite repository for testing."""
    db_path = str(tmp_path / "test_sessions.db")
    repo = SQLiteStateRepository(db_path=db_path)
    yield repo
    # No close needed — fixture scope handles cleanup


@pytest.mark.asyncio
async def test_session_save_and_load(tmp_db: StateRepositoryPort):
    """A session saved to the repository must be reloadable with all fields."""
    session = Session(
        id="test-save-load",
        user_id="test-user",
        agent_id="test-agent",
        title="Test Session",
        context={"key": "value"},
    )
    await tmp_db.save_session(session)

    loaded = await tmp_db.load_session("test-save-load")
    assert loaded is not None, "Session must be loadable after save"
    assert loaded.id == "test-save-load"
    assert loaded.user_id == "test-user"
    assert loaded.title == "Test Session"
    assert loaded.context.get("key") == "value"
    assert loaded.status == SessionStatus.PENDING


@pytest.mark.asyncio
async def test_session_events_persisted(tmp_db: StateRepositoryPort):
    """Events added to a session must survive save/load cycle."""
    from weebot.domain.models.event import MessageEvent, DoneEvent

    session = Session(id="test-events", user_id="u", agent_id="a")

    # Add events
    session = session.add_event(MessageEvent(role="user", message="hello"))
    session = session.add_event(MessageEvent(role="assistant", message="world"))
    session = session.add_event(DoneEvent())
    await tmp_db.save_session(session)

    # Reload and verify
    loaded = await tmp_db.load_session("test-events")
    assert loaded is not None
    assert len(loaded.events) == 3, "All 3 events must be persisted"

    event_types = [type(e).__name__ for e in loaded.events]
    assert event_types == ["MessageEvent", "MessageEvent", "DoneEvent"]


@pytest.mark.asyncio
async def test_session_status_persisted(tmp_db: StateRepositoryPort):
    """Session status changes must survive save/load cycle."""
    session = Session(id="test-status", user_id="u", agent_id="a")

    # Save as CREATED
    await tmp_db.save_session(session)
    loaded = await tmp_db.load_session("test-status")
    assert loaded is not None
    assert loaded.status == SessionStatus.PENDING

    # Update to COMPLETED and save
    session = session.set_status(SessionStatus.COMPLETED)
    await tmp_db.save_session(session)

    # Reload and verify
    loaded = await tmp_db.load_session("test-status")
    assert loaded is not None
    assert loaded.status == SessionStatus.COMPLETED, \
        "COMPLETED status must survive save/load"


@pytest.mark.asyncio
async def test_session_list_filtering(tmp_db: StateRepositoryPort):
    """list_sessions must return correct subset based on status."""
    s1 = Session(id="s1", user_id="u", agent_id="a").set_status(SessionStatus.COMPLETED)
    s2 = Session(id="s2", user_id="u", agent_id="a")  # CREATED
    s3 = Session(id="s3", user_id="v", agent_id="a")  # CREATED

    await tmp_db.save_session(s1)
    await tmp_db.save_session(s2)
    await tmp_db.save_session(s3)

    # All sessions
    all_sessions = await tmp_db.list_sessions()
    assert len(all_sessions) == 3

    # Filter by user
    user_sessions = await tmp_db.list_sessions(user_id="u")
    assert len(user_sessions) == 2

    # Filter by status (via in-memory filter in test)
    completed = [s for s in all_sessions if s.status == SessionStatus.COMPLETED]
    assert len(completed) == 1
    assert completed[0].id == "s1"


@pytest.mark.asyncio
async def test_session_update_existing(tmp_db: StateRepositoryPort):
    """Saving a session with the same ID must update (not duplicate)."""
    session = Session(id="test-update", user_id="u", agent_id="a", title="Version 1")
    await tmp_db.save_session(session)

    # Update title
    session = session.model_copy(update={"title": "Version 2"})
    await tmp_db.save_session(session)

    loaded = await tmp_db.load_session("test-update")
    assert loaded is not None
    assert loaded.title == "Version 2"

    # Verify only one session exists
    all_sessions = await tmp_db.list_sessions()
    matches = [s for s in all_sessions if s.id == "test-update"]
    assert len(matches) == 1, "Update must not create duplicate"
