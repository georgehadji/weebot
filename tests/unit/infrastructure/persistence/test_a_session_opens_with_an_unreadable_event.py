"""One stored event the build cannot rebuild must not make its whole session unopenable.

The console reported "Couldn't open this session / An internal error occurred" for a
session that had run to 2536 events. `GET /api/sessions/{id}` 500ed in
`_row_to_session`: it rebuilt each stored event through the `AgentEvent` union and,
when that failed, fell back to `MessageEvent(**raw)` — which raises for anything that
is not a message payload. `ReviewingState` yields `CorrectionPatternDetected` (a
`DomainEvent`, not a `BaseEvent`), `EventPublisher.emit` appends every yielded event to
`Session.events`, and the union had no member for it, so any session that recorded a
recurring correction could never be loaded again.

Two faults, two tests: the union now covers the domain events flows persist, and an
event it still cannot read is dropped with a warning instead of failing the load.
"""

from __future__ import annotations

import json

import aiosqlite
import pytest

from weebot.domain.models.event import (
    AgentEvent,
    CorrectionPatternDetected,
    MessageEvent,
    SkillEditAccepted,
    SkillEditRejected,
)
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


def _correction_event(session_id: str = "s1") -> CorrectionPatternDetected:
    return CorrectionPatternDetected(
        session_id=session_id,
        category="missing_info",
        count=3,
        sample_step_description="[python_execute] Re-run the algorithm and print its output",
    )


def test_domain_events_a_flow_yields_round_trip_through_a_session():
    """`Session.events` is the persisted list, so the wire form must reload as itself."""
    events = [
        MessageEvent(session_id="s1", role="assistant", message="hello"),
        _correction_event(),
        SkillEditAccepted(session_id="s1", skill_name="s", old_version=1, new_version=2,
                          validation_score_delta=0.1),
        SkillEditRejected(session_id="s1", skill_name="s", skill_version=2, score_drop=0.2),
    ]
    session = Session(id="s1", user_id="u", agent_id="a")
    for event in events:
        session = session.add_event(event)

    # add_event uses model_copy(update=...), which skips validation; a reload does not.
    reloaded = Session.model_validate(session.model_dump(mode="json"))

    assert [e.type for e in reloaded.events] == [e.type for e in events]
    assert isinstance(reloaded.events[1], CorrectionPatternDetected)


@pytest.mark.parametrize(
    ("event_cls", "type_name"),
    [
        (CorrectionPatternDetected, "correction_pattern_detected"),
        (SkillEditAccepted, "skill_edit_accepted"),
        (SkillEditRejected, "skill_edit_rejected"),
    ],
)
def test_every_flow_yielded_domain_event_is_in_the_agent_event_union(event_cls, type_name):
    """A member is required: without one the stored copy cannot become a Session event."""
    assert event_cls in AgentEvent.__args__, f"{type_name} cannot be reloaded"
    assert event_cls.model_fields["type"].default == type_name


@pytest.mark.asyncio
async def test_a_stored_correction_event_loads_with_its_session(tmp_path):
    db = str(tmp_path / "s.db")
    repo = SQLiteStateRepository(db_path=db)
    session = Session(id="s1", user_id="u", agent_id="a", title="T")
    session = session.add_event(MessageEvent(session_id="s1", role="assistant", message="hello"))
    session = session.add_event(_correction_event())
    try:
        await repo.save_session(session)
        loaded = await repo.load_session("s1")
    finally:
        await repo.close()

    assert loaded is not None, "the session that contains a correction event did not load"
    assert [e.type for e in loaded.events] == ["message", "correction_pattern_detected"]
    assert isinstance(loaded.events[1], CorrectionPatternDetected)


@pytest.mark.asyncio
async def test_an_event_from_another_build_is_dropped_not_fatal(tmp_path):
    """The log is not all-or-nothing: unknown entries go, the rest of the history stays."""
    db = str(tmp_path / "s.db")
    repo = SQLiteStateRepository(db_path=db)
    session = Session(id="s1", user_id="u", agent_id="a", title="T")
    session = session.add_event(MessageEvent(session_id="s1", role="assistant", message="hello"))
    try:
        await repo.save_session(session)
        async with aiosqlite.connect(db) as conn:
            stored = [
                {"type": "from_a_newer_build", "id": "x", "session_id": "s1", "payload": 1},
                {"type": "message", "id": "y", "session_id": "s1", "role": "assistant",
                 "message": "hello"},
            ]
            await conn.execute(
                "UPDATE sessions SET events_json = ? WHERE id = ?", (json.dumps(stored), "s1")
            )
            await conn.commit()
        loaded = await repo.load_session("s1")
    finally:
        await repo.close()

    assert loaded is not None, "an unknown event type took the whole session down"
    assert [e.type for e in loaded.events] == ["message"]
