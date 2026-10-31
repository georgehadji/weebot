"""One visibility rule for the WebSocket and SSE event streams.

``SessionPresenceEvent`` names the changed session in ``about_session_id`` and leaves
``session_id`` empty, so it travels on the global channel. The WebSocket broadcaster already
sends it only to the session owner's sockets. SSE treated every event with an empty
``session_id`` as public, so a second principal saw the first one's session ids, titles and
status. SSE also cached "allowed" for a session that did not exist yet, and kept it after
another principal created it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from weebot.domain.models.event import SessionPresenceEvent
from weebot.interfaces.web import event_visibility
from weebot.interfaces.web.event_visibility import EventVisibility, presence_owner, visible_to


def _presence(owner: str = "alice") -> SessionPresenceEvent:
    return SessionPresenceEvent(
        about_session_id="s1", owner_user_id=owner, title="Plan a trip", status="running"
    )


def _other_event(session_id: str = "") -> SimpleNamespace:
    return SimpleNamespace(type="notification", session_id=session_id)


# ── the pure rule ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("event", "principal", "enforced", "expected"),
    [
        (_presence("alice"), "alice", True, True),
        (_presence("alice"), "bob", True, False),
        (_presence("alice"), "anonymous", True, False),
        (_presence("alice"), None, True, False),
        (_presence("alice"), "bob", False, True),  # ownership not enforced: everyone
        (_presence(""), "bob", True, True),  # no owner recorded: legacy, visible
        (_other_event(), "bob", True, True),  # a process-level notice
    ],
)
def test_visible_to_table(event, principal, enforced, expected):
    assert visible_to(event, principal, enforced) is expected


def test_presence_owner_is_the_one_rule_the_broadcaster_uses():
    assert presence_owner(_presence("alice"), True) == "alice"
    assert presence_owner(_presence("alice"), False) is None
    assert presence_owner(_other_event(), True) is None


# ── the per-connection SSE filter ───────────────────────────────────────────


class _Sessions:
    """A state repo whose sessions can change owner between events."""

    def __init__(self, owners: dict[str, str | None]):
        self.owners = owners
        self.load_session = AsyncMock(side_effect=self._load)

    async def _load(self, sid: str):
        if sid not in self.owners:
            return None
        return SimpleNamespace(user_id=self.owners[sid])


@pytest.fixture
def caller(monkeypatch):
    """Patch the auth calls the filter makes, so a test names the caller directly."""
    state = {"principal": "bob", "enforced": True}

    async def _principal(_request):
        return state["principal"]

    async def _verify(_request, owner):
        if state["enforced"] and owner and owner != state["principal"]:
            raise HTTPException(status_code=404)

    monkeypatch.setattr(event_visibility, "current_principal", _principal)
    monkeypatch.setattr(event_visibility, "verify_session_ownership", _verify)
    monkeypatch.setattr(event_visibility, "ownership_enforced", lambda: state["enforced"])
    return state


@pytest.mark.asyncio
async def test_sse_hides_another_principals_presence_frame(caller):
    visible = EventVisibility(request=object(), state_repo=_Sessions({}))
    assert await visible(_presence("alice")) is False


@pytest.mark.asyncio
async def test_sse_shows_a_principal_their_own_presence_frame(caller):
    caller["principal"] = "alice"
    visible = EventVisibility(request=object(), state_repo=_Sessions({}))
    assert await visible(_presence("alice")) is True


@pytest.mark.asyncio
async def test_sse_shows_presence_frames_when_ownership_is_not_enforced(caller):
    caller["enforced"] = False
    visible = EventVisibility(request=object(), state_repo=_Sessions({}))
    assert await visible(_presence("alice")) is True


@pytest.mark.asyncio
async def test_sse_passes_a_process_level_notice(caller):
    visible = EventVisibility(request=object(), state_repo=_Sessions({}))
    assert await visible(_other_event()) is True


@pytest.mark.asyncio
async def test_sse_hides_a_session_event_of_another_principal_and_caches_the_verdict(caller):
    repo = _Sessions({"s1": "alice"})
    visible = EventVisibility(request=object(), state_repo=repo)
    assert await visible(_other_event("s1")) is False
    assert await visible(_other_event("s1")) is False
    assert repo.load_session.await_count == 1  # one lookup per session per connection


@pytest.mark.asyncio
async def test_sse_does_not_keep_an_allow_given_before_the_session_existed(caller):
    repo = _Sessions({})
    visible = EventVisibility(request=object(), state_repo=repo)
    assert await visible(_other_event("s9")) is True  # not saved yet: nothing to check
    repo.owners["s9"] = "alice"  # then another principal creates it
    assert await visible(_other_event("s9")) is False
