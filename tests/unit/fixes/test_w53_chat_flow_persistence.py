"""W5.3 (F28): ChatFlow takes its session persistence adapter as an argument.

ChatFlow used to look it up lazily with a bare `Container()` that never ran
`configure_defaults()`, so `get("session_persistence")` always raised KeyError
and every chat save skipped the retrying SessionPersistenceAdapter for a plain
`state_repo.save_session`. The container now passes the adapter in.
"""

from __future__ import annotations

from weebot.application.flows.chat_flow import ChatFlow
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session


class _Saver:
    def __init__(self):
        self.saved = []

    async def save_session(self, session):
        self.saved.append(session.id)
        return True


def _event():
    return MessageEvent(message="hi")


async def test_an_injected_adapter_saves_each_event(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("ChatFlow built a Container")

    monkeypatch.setattr("weebot.application.di.Container", _boom)
    adapter, repo = _Saver(), _Saver()
    flow = ChatFlow(
        llm=None, session=Session(id="c1"), state_repo=repo, persistence_adapter=adapter
    )
    await flow._emit(_event())
    assert adapter.saved == ["c1"] and repo.saved == []


async def test_without_an_adapter_it_saves_through_the_repo(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("ChatFlow built a Container")

    monkeypatch.setattr("weebot.application.di.Container", _boom)
    repo = _Saver()
    flow = ChatFlow(llm=None, session=Session(id="c2"), state_repo=repo)
    await flow._emit(_event())
    assert repo.saved == ["c2"]


def test_the_container_passes_its_adapter_to_chat_flows():
    from weebot.application.di import Container
    from weebot.infrastructure.persistence.session_persistence_adapter import (
        SessionPersistenceAdapter,
    )

    c = Container()
    c.configure_defaults()
    built = c.build_chat_flow(Session(id="c3"))
    assert isinstance(built._persistence_adapter, SessionPersistenceAdapter)
