"""Deleting a session purges every store that holds its data.

Built against a REAL configured Container, because the defect lived entirely
in wiring: build_deletion_orchestrator looked up EventStorePort from the wrong
module and two stores by concrete classes nothing registered, and each failure
was swallowed by `except (KeyError, Exception): pass`. With mocks every lookup
succeeds. Against the real container, the orchestrator purged the knowledge
graph and nothing else -- the event store kept a deleted session's full event
journal and the Telegram gateway kept its session map.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.session_deletion_orchestrator import (
    SessionDeletionOrchestrator,
)
from weebot.domain.models.session import Session
from weebot.interfaces.web.dependencies import build_deletion_orchestrator

# Every store a web session writes, besides the state repo. The checkpoint
# store is not among them: see test_nothing_writes_checkpoints_so_none_are_purged.
_SESSION_STORES = {"event_store", "gateway_session_store", "knowledge_graph"}


# Container construction imports the whole application -- 20-30s cold on
# Windows. Build it once for the module.
@pytest.fixture(scope="module")
def container():
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    return c


def _orchestrator(container) -> SessionDeletionOrchestrator:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))
    return build_deletion_orchestrator(request, container.get(StateRepositoryPort))


@pytest.mark.timeout(360)
def test_every_store_holding_session_data_is_wired_for_purging(container):
    assert set(_orchestrator(container).store_names) == _SESSION_STORES


@pytest.mark.timeout(360)
def test_a_deletion_reaches_every_store(container):
    """Each purge method actually runs against the real stores. A session id
    that exists nowhere is deleted, so no real data is touched."""
    results = asyncio.run(_orchestrator(container).delete_session(f"test-{uuid.uuid4()}"))

    assert results == {"state_repo": "ok", **{name: "ok" for name in _SESSION_STORES}}


@pytest.mark.timeout(360)
def test_nothing_writes_checkpoints_so_none_are_purged(container):
    """The recorded decision, enforced. The flow checkpoint store is not purged
    because no production flow is given a checkpoint_port. If that changes,
    this fails -- and the store must be added to dependencies._session_stores
    in the same change, or deleted sessions leave their checkpoints behind."""
    from weebot.application.services.task_runner import TaskRunner

    runner = container.get(TaskRunner)
    flow = runner.create_plan_act_factory(llm=MagicMock(), tools=ToolCollection())(
        Session(id="web-1", user_id="u", agent_id="a")
    )
    assert flow._checkpoint_port is None

    from weebot.application.ports.checkpoint_port import CheckpointPort

    with pytest.raises(KeyError):
        container.get(CheckpointPort)


def test_a_store_without_the_purge_method_is_refused_at_wiring_time():
    """Deletion used to report such a store "ok" with nothing called."""
    orch = SessionDeletionOrchestrator(state_repo=MagicMock())

    with pytest.raises(TypeError, match="delete_session"):
        orch.add_store("broken", object(), "delete_session")
