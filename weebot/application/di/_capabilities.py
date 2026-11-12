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
        # One run per Idempotency-Key for the OpenAI-compatible API (H12b).
        from weebot.application.ports.idempotency_port import IdempotencyPort
        from weebot.infrastructure.persistence.idempotency_store import SQLiteIdempotencyStore

        idempotency_db = str(Path(db_path).parent / "api_idempotency.db")
        self.register(IdempotencyPort, lambda: SQLiteIdempotencyStore(db_path=idempotency_db))
        # Undoable workspace file checkpoints, bound always so a session delete purges them
        # whether or not WEEBOT_FILE_CHECKPOINTS is on now (H5).
        from weebot.application.ports.workspace_checkpoint_port import WorkspaceCheckpointPort
        from weebot.infrastructure.checkpoints.shadow_git import (
            DEFAULT_CHECKPOINT_DIR,
            ShadowGitCheckpointAdapter,
        )

        self.register(
            WorkspaceCheckpointPort, lambda: ShadowGitCheckpointAdapter(DEFAULT_CHECKPOINT_DIR)
        )
        # Tool output too long for the context, kept on disk (H7); a session delete purges it.
        from weebot.application.ports.spillover_store_port import SpilloverStorePort
        from weebot.infrastructure.spillover.file_store import FileSpilloverStore

        self.register(SpilloverStorePort, lambda: FileSpilloverStore())
        # What file_editor last showed the model of each file, and its syntax check (H6).
        from weebot.application.ports.syntax_check_port import SyntaxCheckPort
        from weebot.application.services.file_state import FileStateRegistry
        from weebot.infrastructure.adapters.syntax_check import InProcessSyntaxCheck

        self.register(FileStateRegistry, FileStateRegistry)
        self.register(SyntaxCheckPort, InProcessSyntaxCheck)
        # One Python interpreter per session that keeps its variables between calls (H17).
        from weebot.application.services.kernel_manager import KernelManager

        self.register(KernelManager, self._create_kernel_manager)
        # The persistent-memory text each session read at its first step (H24a).
        from weebot.application.di.keys import MEMORY_SNAPSHOT_CACHE

        self.register(MEMORY_SNAPSHOT_CACHE, self._create_memory_snapshot_cache)
        from weebot.application.di.keys import PROMPT_PREFIX_STORE

        self.register(PROMPT_PREFIX_STORE, self._create_prompt_prefix_store)
        from weebot.application.di.keys import STRATEGY_TRANSFER

        strategies_db = Path(db_path).parent / "improvement_strategies.db"
        self.register(STRATEGY_TRANSFER, lambda: self._create_strategy_transfer(strategies_db))

    @staticmethod
    def _create_kernel_manager():
        from weebot.application.services.kernel_manager import KernelManager
        from weebot.config.settings import get_settings
        from weebot.infrastructure.sandbox.factory import build_sandbox_config
        from weebot.infrastructure.sandbox.native_kernel import NativeKernel

        return KernelManager(NativeKernel(build_sandbox_config(get_settings())))

    @staticmethod
    def _create_memory_snapshot_cache():
        from weebot.application.services.memory_snapshot_cache import MemorySnapshotCache
        from weebot.config.feature_flags import is_enabled
        from weebot.tools.persistent_memory import PersistentMemoryTool

        return MemorySnapshotCache(
            PersistentMemoryTool.load_snapshot,
            frozen=lambda: is_enabled("MEMORY_SNAPSHOT_FREEZE_ENABLED"),
        )

    @staticmethod
    def _create_prompt_prefix_store():
        from weebot.infrastructure.adapters.prompt_prefix_store import InMemoryPromptPrefixStore
        from weebot.infrastructure.observability.metrics import prompt_prefix_changes_total

        return InMemoryPromptPrefixStore(
            on_change=lambda reason: prompt_prefix_changes_total.labels(reason=reason).inc()
        )

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
