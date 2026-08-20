"""Tests for SessionScopedEventBus (Phase 0, T0.2).

Verifies:
  1. publish() stamps session_id when the event's id is empty.
  2. publish() does not overwrite an already-stamped session_id.
  3. publish_domain_event() passes through unchanged (domain events are
     not part of the wire transport this decorator targets).
  4. subscribe/unsubscribe/subscribe_domain/unsubscribe_domain delegate
     straight through to the inner bus.
"""

from __future__ import annotations

import pytest

from weebot.application.services.session_scoped_event_bus import SessionScopedEventBus
from weebot.domain.models.event import FactDiscovered, MessageEvent


class _RecordingBus:
    """Minimal EventBusPort stand-in that records calls."""

    def __init__(self) -> None:
        self.published: list = []
        self.published_domain: list = []
        self.subscribed: list = []
        self.subscribed_domain: list = []

    async def publish(self, event) -> None:
        self.published.append(event)

    async def publish_domain_event(self, event) -> None:
        self.published_domain.append(event)

    def subscribe(self, handler) -> None:
        self.subscribed.append(handler)

    def subscribe_domain(self, handler) -> None:
        self.subscribed_domain.append(handler)

    def unsubscribe(self, handler) -> None:
        self.subscribed.remove(handler)

    def unsubscribe_domain(self, handler) -> None:
        self.subscribed_domain.remove(handler)


@pytest.mark.asyncio
async def test_publish_stamps_session_id_when_empty():
    inner = _RecordingBus()
    bus = SessionScopedEventBus(inner, session_id="sess-1")

    await bus.publish(MessageEvent(role="user", message="hi"))

    assert len(inner.published) == 1
    assert inner.published[0].session_id == "sess-1"


@pytest.mark.asyncio
async def test_publish_does_not_overwrite_existing_session_id():
    inner = _RecordingBus()
    bus = SessionScopedEventBus(inner, session_id="sess-1")

    await bus.publish(MessageEvent(role="user", message="hi", session_id="already-set"))

    assert inner.published[0].session_id == "already-set"


@pytest.mark.asyncio
async def test_publish_domain_event_passes_through_unchanged():
    inner = _RecordingBus()
    bus = SessionScopedEventBus(inner, session_id="sess-1")
    domain_event = FactDiscovered(session_id="other-session", key="k", value="v")

    await bus.publish_domain_event(domain_event)

    assert inner.published_domain == [domain_event]
    assert inner.published_domain[0].session_id == "other-session"


def test_subscribe_and_unsubscribe_delegate_to_inner_bus():
    inner = _RecordingBus()
    bus = SessionScopedEventBus(inner, session_id="sess-1")

    async def handler(event): ...

    async def domain_handler(event): ...

    bus.subscribe(handler)
    bus.subscribe_domain(domain_handler)
    assert inner.subscribed == [handler]
    assert inner.subscribed_domain == [domain_handler]

    bus.unsubscribe(handler)
    bus.unsubscribe_domain(domain_handler)
    assert inner.subscribed == []
    assert inner.subscribed_domain == []
