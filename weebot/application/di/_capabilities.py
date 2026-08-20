"""Knowledge-graph capability bindings for Container.

Background job registration used to live here too, in a
``register_agentwasp_jobs()`` method that was never called and that built a
*second* ``SchedulingManager`` alongside the DI-managed one.  Job wiring now
has a single home: ``weebot/scheduling/default_jobs.py``, driven by
``weebot/config/jobs.yaml`` and started from the web lifespan.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class CapabilitiesMixin:
    """Knowledge-graph service bindings."""

    def configure_knowledge_graph(self, *, db_path: str = "./weebot_sessions.db") -> None:
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
        self.register("kg_adapter", lambda: self.get(SQLiteKnowledgeGraph))
        self.register("knowledge_graph", lambda: self._create_kg_service())

    def _create_kg_service(self):
        from weebot.application.services.knowledge_graph import KnowledgeGraphService

        return KnowledgeGraphService(adapter=self.get("kg_adapter"))
