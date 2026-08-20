"""Web interface dependency helpers — composition-root infrastructure wiring.

Functions here may import from ``weebot.infrastructure`` because they are
part of the composition root (the outermost layer of the application).
The ``interfaces-no-infra`` import-linter contract exempts this file.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)


def build_deletion_orchestrator(request: Request, state_repo: StateRepositoryPort) -> Any:
    """Build a SessionDeletionOrchestrator with all available stores.

    May import from infrastructure — this is a composition-root function
    that wires up concrete adapters at the outermost layer.
    """
    from weebot.application.services.session_deletion_orchestrator import (
        SessionDeletionOrchestrator,
    )

    orch = SessionDeletionOrchestrator(state_repo=state_repo)
    container = request.app.state.container

    # Event store
    try:
        from weebot.application.ports.event_bus_port import EventStorePort

        event_store = container.get(EventStorePort)
        if hasattr(event_store, "delete_session"):
            orch.add_store("event_store", event_store, "delete_session")
    except (KeyError, Exception):
        pass

    # Checkpoint store
    try:
        from weebot.infrastructure.persistence.checkpoint_store import SQLiteCheckpointStore

        checkpoint_store = container.get(SQLiteCheckpointStore)
        if hasattr(checkpoint_store, "delete"):
            orch.add_store("checkpoint_store", checkpoint_store, "delete")
    except (KeyError, Exception):
        pass

    # Gateway session store
    try:
        from weebot.infrastructure.persistence.gateway_session_store import (
            SQLiteGatewaySessionStore,
        )

        gateway_store = container.get(SQLiteGatewaySessionStore)
        orch.add_store("gateway_session_store", gateway_store, "delete_by_session_id")
    except (KeyError, Exception):
        pass

    # Knowledge graph
    try:
        import importlib as _kg_il

        _kg_mod = _kg_il.import_module("weebot.infrastructure.persistence.sqlite_knowledge_graph")
        _kg_cls = getattr(_kg_mod, "SQLiteKnowledgeGraph", None)
        if _kg_cls is not None:
            kg = container.get(_kg_cls)
            if hasattr(kg, "delete_by_session_id"):
                orch.add_store("knowledge_graph", kg, "delete_by_session_id")
    except (KeyError, Exception):
        pass

    return orch
