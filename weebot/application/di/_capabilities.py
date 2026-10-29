"""Knowledge-graph capability bindings for Container.

Background job registration used to live here too, in a
``register_agentwasp_jobs()`` method that was never called and that built a
*second* ``SchedulingManager`` alongside the DI-managed one.  Job wiring now
has a single home: ``weebot/scheduling/default_jobs.py``, driven by
``weebot/config/jobs.yaml`` and started from the web lifespan.
"""

from __future__ import annotations

import logging
from weebot.config.constants import DB_SESSIONS_PATH

logger = logging.getLogger(__name__)


class CapabilitiesMixin:
    """Knowledge-graph service bindings."""

    def configure_knowledge_graph(self, *, db_path: str = DB_SESSIONS_PATH) -> None:
        """Register the knowledge-graph adapter and service.

        Called from ``configure_defaults()``.  The bindings are lazy, so
        registering them costs nothing until something resolves them — the
        SQLite file is only touched on first ``get()``.

        The adapter is registered under its concrete class *and* under
        ``"kg_adapter"``: the session-deletion cascade in
        ``interfaces/web/dependencies.py`` resolves it by class, so a
        string-only binding left that cascade silently skipping the graph.
        """
        from weebot.infrastructure.persistence.sqlite_knowledge_graph import SQLiteKnowledgeGraph

        self.register(SQLiteKnowledgeGraph, lambda: SQLiteKnowledgeGraph(db_path=db_path))
        # The graph follows WEEBOT_DB_BACKEND like the state repository does.
        self.register("kg_adapter", self._create_kg_adapter)
        self.register("knowledge_graph", lambda: self._create_kg_service())
        # Episodic summaries (WEEBOT_EPISODIC_SUMMARIES gates their use, not this
        # binding: a session deleted after the flag was turned off is still purged).
        from pathlib import Path

        from weebot.application.di.keys import SUMMARY_REPO
        from weebot.infrastructure.persistence.sqlite_summary_repo import SQLiteSummaryRepository

        summaries_db = str(Path(db_path).parent / "episodic_summaries.db")
        self.register(SUMMARY_REPO, lambda: SQLiteSummaryRepository(db_path=summaries_db))
        # Flow checkpoints, bound always for the same reason (WEEBOT_FLOW_CHECKPOINTS).
        from weebot.application.ports.checkpoint_port import CheckpointPort
        from weebot.infrastructure.persistence.checkpoint_store import SQLiteCheckpointStore

        checkpoints_db = str(Path(db_path).parent / "flow_checkpoints.db")
        self.register(CheckpointPort, lambda: SQLiteCheckpointStore(db_path=checkpoints_db))
        from weebot.application.di.keys import STRATEGY_TRANSFER

        strategies_db = Path(db_path).parent / "improvement_strategies.db"
        self.register(STRATEGY_TRANSFER, lambda: self._create_strategy_transfer(strategies_db))

    @staticmethod
    def _create_strategy_transfer(db_path):
        """StrategyTransferService over its store, or None while WEEBOT_STRATEGY_TRANSFER is off."""
        from weebot.config import feature_flags

        if not feature_flags.STRATEGY_TRANSFER_ENABLED:
            return None
        from weebot.application.services.strategy_transfer import StrategyTransferService
        from weebot.infrastructure.persistence.strategy_store import StrategyStore

        return StrategyTransferService(StrategyStore(db_path=db_path))

    def _create_kg_adapter(self):
        if self._db_backend() == "postgresql":  # type: ignore[attr-defined]
            from weebot.infrastructure.persistence.postgresql.knowledge_graph import (
                PostgreSQLKnowledgeGraph,
            )

            return PostgreSQLKnowledgeGraph()
        from weebot.infrastructure.persistence.sqlite_knowledge_graph import SQLiteKnowledgeGraph

        return self.get(SQLiteKnowledgeGraph)

    def _create_kg_service(self):
        from weebot.application.services.knowledge_graph import KnowledgeGraphService

        return KnowledgeGraphService(adapter=self.get("kg_adapter"))
