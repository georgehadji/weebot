"""AgentWasp capabilities + scheduler bindings mixin for Container."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class CapabilitiesMixin:
    """AgentWasp capability services + background job registration."""

    def configure_agentwasp_capabilities(self, *, db_path="./weebot_sessions.db"):
        self.register("kg_adapter", lambda: self.__class__._create_kg_adapter(db_path))
        self.register("knowledge_graph", lambda: self._create_kg_service())
        self.register("behavioral_learner", lambda: self._create_behavioral_learner())
        self.register("opportunity_engine", lambda: self._create_opportunity_engine(db_path))

    @staticmethod
    def _create_kg_adapter(db_path: str):
        from weebot.infrastructure.persistence.sqlite_knowledge_graph import (
            SQLiteKnowledgeGraph,
        )
        return SQLiteKnowledgeGraph(db_path=db_path)

    def _create_kg_service(self):
        from weebot.application.services.knowledge_graph import KnowledgeGraphService
        adapter = self.get("kg_adapter")
        return KnowledgeGraphService(adapter=adapter)

    def _create_behavioral_learner(self):
        from weebot.application.services.behavioral_learner import BehavioralLearner
        from weebot.application.ports.llm_port import LLMPort
        return BehavioralLearner(llm=self._maybe_get(LLMPort))

    def _create_opportunity_engine(self, db_path: str):
        from weebot.application.services.opportunity_engine import OpportunityEngine
        return OpportunityEngine(
            knowledge_graph=self._maybe_get_str("knowledge_graph"),
            fts5_search=self._maybe_get_str("fts5_search"),
        )

    async def register_agentwasp_jobs(self, scheduler_db="./weebot_jobs.db"):
        from weebot.scheduling.scheduler import SchedulingManager
        import subprocess, shutil
        from pathlib import Path

        mgr = SchedulingManager(db_path=scheduler_db)
        kg = self._maybe_get_str("knowledge_graph")
        if kg is not None:
            async def kg_consolidation():
                stats = await kg.get_stats()
                logger.info("KG consolidation: %s", stats)
            mgr.register_callable("kg_consolidation", kg_consolidation)
        opp = self._maybe_get_str("opportunity_engine")
        if opp is not None:
            async def opportunity_scan():
                proposals = await opp.scan()
                logger.info("Opportunity scan: %d proposals", len(proposals))
            mgr.register_callable("opportunity_scan", opportunity_scan)
        learner = self._maybe_get_str("behavioral_learner")
        if learner is not None:
            async def behavioral_consolidation():
                rules = await learner.get_active_rules()
                logger.info("Behavioral consolidation: %d active rules", len(rules))
            mgr.register_callable("behavioral_consolidation", behavioral_consolidation)
        async def integrity_check():
            issues = []
            try:
                result = await asyncio.to_thread(
                    lambda: subprocess.run(
                        ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10,
                    )
                )
                if result.stdout.strip():
                    issues.append(f"Uncommitted changes: {result.stdout.count(chr(10))} files")
            except Exception as e:
                issues.append(f"Git check failed: {e}")
            total, used, free = shutil.disk_usage(Path.cwd())
            if free // (2**30) < 1:
                issues.append("Low disk space")
            logger.info("Integrity check: %s", issues or "all clear")
        mgr.register_callable("integrity_check", integrity_check)
        async def memory_cleanup():
            logger.info("Memory cleanup: archival not yet implemented")
        mgr.register_callable("memory_cleanup", memory_cleanup)

        # ── Self-Harness weekly evolution ────────────────────────────
        async def self_harness_evolve():
            try:
                from weebot.application.flows.harness_opt_flow import HarnessOptFlow
                from weebot.application.services.harness_optimization_target import (
                    HarnessOptimizationTarget,
                )
                from weebot.infrastructure.persistence.trajectory_repo import (
                    TrajectoryRepository,
                )
                from weebot.application.ports.llm_port import LLMPort

                llm_port = self._maybe_get(LLMPort)
                if llm_port is None:
                    logger.warning("Self-Harness skipped: no LLM configured")
                    return

                target = HarnessOptimizationTarget()
                await target.load()
                trajectory_repo = TrajectoryRepository()

                flow = HarnessOptFlow(
                    llm=llm_port,
                    target=target,
                    trajectory_repo=trajectory_repo,
                    flow_factory=lambda s: None,  # Stub — mining only
                    max_proposals=3,
                )
                async for event in flow.run():
                    if hasattr(event, "message") and event.message:
                        logger.info("Self-Harness: %s", event.message)

                await trajectory_repo.close()
                logger.info("Self-Harness weekly evolution complete")
            except Exception as exc:
                logger.error("Self-Harness weekly failed: %s", exc, exc_info=True)

        mgr.register_callable("self_harness_evolve", self_harness_evolve)

        await mgr.load_from_config()
        await mgr.start()
