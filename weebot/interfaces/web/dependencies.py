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
# The flow checkpoint store is here since D4 wired it (WEEBOT_FLOW_CHECKPOINTS);
# it is purged whether or not the flag is on now, since it may have been earlier.
def _session_stores() -> list[tuple[str, Any, str]]:
    from weebot.application.di.keys import SUMMARY_REPO
    from weebot.application.ports.checkpoint_port import CheckpointPort
    from weebot.application.ports.event_store_port import EventStorePort
    from weebot.application.ports.gateway_session_store_port import IGatewaySessionStorePort

    return [
        # DurableEventBus journals every agent event of the session here.
        ("event_store", EventStorePort, "delete_session"),
        # The Telegram gateway's chat -> session mapping.
        ("gateway_session_store", IGatewaySessionStorePort, "delete_by_session_id"),
        # Entities and relations extracted during the session.
        ("knowledge_graph", "kg_adapter", "delete_by_session_id"),
        # What a successful session did, kept for planning similar tasks.
        ("episodic_summaries", SUMMARY_REPO, "delete_by_session_id"),
        # The plan snapshot after each step, for recovering an interrupted run.
        ("flow_checkpoints", CheckpointPort, "delete"),
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
