"""Web interface dependency helpers — composition-root wiring.

Stores are resolved from the DI container by port, so this module imports no
infrastructure.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from weebot.application.ports.state_repo_port import StateRepositoryPort

logger = logging.getLogger(__name__)


# Every store that holds a web session's data, as (name, container key,
# purge method). Container keys, not concrete classes: a lookup by concrete
# class that nothing registered raised KeyError into a bare `except: pass`,
# which is how the checkpoint and gateway purges never ran.
#
# Deliberately absent: the flow checkpoint store (SQLiteCheckpointStore).
# Nothing in production writes it -- no PlanActFlowConfig is built with a
# checkpoint_port, so CheckpointScheduler returns early and flow_checkpoints
# stays empty. test_session_deletion_wiring fails if CheckpointPort is ever
# registered without a purge being added here.
def _session_stores() -> list[tuple[str, Any, str]]:
    from weebot.application.ports.event_store_port import EventStorePort
    from weebot.application.ports.gateway_session_store_port import IGatewaySessionStorePort

    return [
        # DurableEventBus journals every agent event of the session here.
        ("event_store", EventStorePort, "delete_session"),
        # The Telegram gateway's chat -> session mapping.
        ("gateway_session_store", IGatewaySessionStorePort, "delete_by_session_id"),
        # Entities and relations extracted during the session.
        ("knowledge_graph", "kg_adapter", "delete_by_session_id"),
    ]


def build_deletion_orchestrator(request: Request, state_repo: StateRepositoryPort) -> Any:
    """Build a SessionDeletionOrchestrator over every store holding session data.

    A store that cannot be resolved is logged, not skipped silently: the
    deletion still runs for the others, and the log names what was left.
    """
    from weebot.application.services.session_deletion_orchestrator import (
        SessionDeletionOrchestrator,
    )

    orch = SessionDeletionOrchestrator(state_repo=state_repo)
    container = request.app.state.container

    for name, key, method in _session_stores():
        try:
            orch.add_store(name, container.get(key), method)
        except Exception:
            # Unresolvable, or resolved to something without the purge method.
            logger.warning(
                "Session deletion will not purge %s: it could not be wired",
                name,
                exc_info=True,
            )

    return orch
