"""D50 — which events reach the global WebSocket channel.

Candidate D50 from Wave 6 (`tasks/audits/defect_hunt_w6_interfaces.md`), left
uninvestigated there and recorded as *"events without session_id broadcast to
all global connections"*, with residual risk R-2: *"D50 may be the same leak by
another path. If the broadcaster fans unscoped events to all connections,
fixing the subscription check does not stop the delivery."*

**Investigating it did not confirm a defect, and these tests record why.**
``session_id == "" ⇒ global`` is a documented routing contract, not an
oversight — ``SessionPresenceEvent`` states it in its own docstring and depends
on it to feed a rail that watches every session. R-2's premise held (the
broadcaster does fan unscoped events out) but its conclusion did not: session
events *are* stamped, by ``SessionScopedEventBus``, at every flow construction
on the web path.

What the investigation did find is narrower and latent: the one production
converter that builds an event from a caller's arbitrary payload dropped
``session_id`` on its fallback branch, which by the rule above would have put
that payload on the global channel. It has no production caller today —
``EventBrokerAdapter`` is constructed only in tests — so this is a hole closed
before anyone fell in it, not a leak that was open.

These tests pin the contract in both directions, so that a future change which
makes the rule accidental again is visible.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.event import (
    MessageEvent,
    NotificationEvent,
    SessionPresenceEvent,
)
from weebot.infrastructure.events.broker_adapter import EventBrokerAdapter
from weebot.infrastructure.event_bus import AsyncEventBus


class TestTheRoutingContract:
    """`session_id` is a transport correlation id, and empty means global."""

    def test_base_event_session_id_defaults_to_empty(self):
        """The default is what makes an unstamped event globally routable."""
        assert MessageEvent(role="assistant", message="hi").session_id == ""

    def test_session_presence_deliberately_leaves_it_empty(self):
        """It names its subject in `about_session_id` precisely so it can go global.

        This is why the fix for D50 is not "never broadcast unscoped events":
        a documented feature depends on that route.
        """
        event = SessionPresenceEvent(about_session_id="s-1", status="running", title="t")
        assert event.session_id == ""
        assert event.about_session_id == "s-1"


class TestBrokerAdapterCarriesScope:
    """The latent hole: a converter that dropped the correlation id."""

    @pytest.fixture
    def adapter(self) -> EventBrokerAdapter:
        return EventBrokerAdapter(event_bus=AsyncEventBus())

    def test_fallback_notification_carries_the_session_id(self, adapter):
        """Arbitrary caller payload must stay on its own session's channel.

        The text embeds up to 200 characters of `data`. Without `session_id`
        this event routes to every authenticated `/ws` client.
        """
        event = adapter._convert("anything_unmapped", "agent-7", {"session_id": "s-42", "x": 1})
        assert isinstance(event, NotificationEvent)
        assert event.session_id == "s-42"

    def test_fallback_still_embeds_the_payload(self, adapter):
        """No behaviour was removed -- only the routing was corrected."""
        event = adapter._convert("custom", "agent-7", {"session_id": "s-42", "secret": "value"})
        assert "custom" in event.text
        assert "agent-7" in event.text

    def test_a_caller_omitting_session_id_still_yields_empty(self, adapter):
        """Honest about the remaining edge: the converter cannot invent scope.

        It propagates what it is given. A caller that omits `session_id` still
        produces a globally-routable event -- see the residual risk in
        tasks/audits/review_gate_d47_d50.md.
        """
        assert adapter._convert("custom", "agent-7", {"x": 1}).session_id == ""

    def test_fact_discovered_carries_scope_too(self, adapter):
        """The branch that was already correct, pinned so it stays that way."""
        event = adapter._convert(
            "fact_discovered", "working_memory", {"session_id": "s-9", "key": "k", "value": "v"}
        )
        assert event.session_id == "s-9"
