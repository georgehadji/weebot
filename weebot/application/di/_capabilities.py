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
        # ── Memory salience sweep (hourly) ────────────────────────
        async def memory_salience_sweep():
            try:
                from weebot.application.services.memory_lifecycle_service import MemoryLifecycleService
                from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
                repo = SQLiteStateRepository()
                svc = MemoryLifecycleService()
                stats = await svc.sweep(repo=repo)
                logger.info(
                    "Memory salience sweep: checked=%d, evicted=%d",
                    stats["checked"], stats["evicted"],
                )
            except Exception as exc:
                logger.warning("Memory salience sweep failed: %s", exc, exc_info=True)
        mgr.register_callable("memory_salience_sweep", memory_salience_sweep)

        # ── Commitment heartbeat ──────────────────────────────────
        from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
        _cmt_repo = SQLiteStateRepository(db_path=str(Path("./weebot_sessions.db")))
        async def commitment_heartbeat():
            try:
                from weebot.domain.services.commitment_engine import CommitmentEngine
                engine = CommitmentEngine(state_repo=_cmt_repo)
                stats = await engine.heartbeat()
                logger.info(
                    "Commitment heartbeat: checked=%d, overdue=%d, pending=%d",
                    stats["checked"], stats["marked_overdue"], stats["active_pending"],
                )
            except Exception as exc:
                logger.warning("Commitment heartbeat failed: %s", exc, exc_info=True)
        mgr.register_callable("commitment_heartbeat", commitment_heartbeat)

        # ── User-model consolidation (replaces stub) ──────────────
        async def behavioral_consolidation():
            try:
                from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
                repo = SQLiteStateRepository()
                from weebot.application.services.user_model_consolidator import UserModelConsolidator
                consolidator = UserModelConsolidator(state_repo=repo)
                profile = await consolidator.consolidate()
                logger.info(
                    "User-model consolidation: profile (%d chars, %d words)",
                    len(profile), len(profile.split()),
                )
            except Exception as exc:
                logger.warning("User-model consolidation failed: %s", exc, exc_info=True)
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

        # ── Skill promotion check (daily) ───────────────────────────
        async def skill_promotion_check():
            try:
                from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
                repo = SQLiteStateRepository()
                # Load all candidate skills (trust=candidate) from skill store
                from weebot.infrastructure.persistence.skill_store import SkillStore
                store = SkillStore()
                candidates = [s for s in await store.list_all() if s.metadata.trust == "candidate"]
                if not candidates:
                    logger.debug("Skill promotion: no candidate skills found")
                    return
                promoted = 0
                for skill in candidates:
                    try:
                        from weebot.domain.services.skill_promotion_gate import SkillPromotionGate
                        gate = SkillPromotionGate(
                            chain_of_verification=None,  # will be lazy-initialized
                            harness_scorer=None,
                        )
                        result = await gate.evaluate(skill)
                        if result.passed:
                            updated = skill.with_trust("trusted")
                            await store.save(updated)
                            promoted += 1
                            logger.info("Promoted skill %s to trusted (verify=%.2f, harness=%.2f)",
                                        skill.name, result.verify_score, result.harness_score)
                    except Exception as exc:
                        logger.debug("Skill promotion check skipped for %s: %s", skill.name, exc)
                logger.info("Skill promotion: %d/%d candidates promoted", promoted, len(candidates))
            except Exception as exc:
                logger.warning("Skill promotion check failed: %s", exc, exc_info=True)
        mgr.register_callable("skill_promotion_check", skill_promotion_check)

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
                from weebot.interfaces.factories import build_tools, create_flow

                llm_port = self._maybe_get(LLMPort)
                if llm_port is None:
                    logger.warning("Self-Harness skipped: no LLM configured")
                    return

                # Load evaluation tasks
                import yaml
                from pathlib import Path
                eval_tasks_path = Path("weebot/config/harness/eval_tasks.yaml")
                if eval_tasks_path.exists():
                    with open(eval_tasks_path) as f:
                        task_cfg = yaml.safe_load(f)
                    held_in = task_cfg.get("held_in_tasks", [])
                    held_out = task_cfg.get("held_out_tasks", [])
                else:
                    logger.warning("eval_tasks.yaml not found — Self-Harness will only mine")
                    held_in = []
                    held_out = []

                # Build shared tools and flow factory for RegressionGate
                tools = await build_tools(role="admin", llm_port=llm_port)

                # Cheap surrogate signal for fast-reject in RegressionGate
                from weebot.application.services.code_quality_signal import (
                    CodeQualitySignal,
                )
                code_quality_signal = CodeQualitySignal(llm=llm_port)

                async def _eval_flow_factory(session):
                    return create_flow(
                        flow_type="plan_act",
                        session=session,
                        llm=llm_port,
                        tools=tools,
                    )

                # Cascade models to evolve independently
                from weebot.config.model_refs import (
                    MODEL_CASCADE_TIER1, MODEL_CASCADE_TIER2,
                    MODEL_CASCADE_TIER3, MODEL_CASCADE_TIER4,
                    get_harness_for_model,
                )
                cascade_models = [
                    MODEL_CASCADE_TIER1,
                    MODEL_CASCADE_TIER2,
                    MODEL_CASCADE_TIER3,
                    MODEL_CASCADE_TIER4,
                ]

                for model_id in cascade_models:
                    logger.info("Self-Harness: evolving harness for %s", model_id)
                    trajectory_repo = TrajectoryRepository()

                    target = HarnessOptimizationTarget(
                        model_id=model_id,
                    )
                    await target.load()

                    flow = HarnessOptFlow(
                        llm=llm_port,
                        target=target,
                        trajectory_repo=trajectory_repo,
                        tools=tools,
                        held_in_tasks=held_in,
                        held_out_tasks=held_out,
                        max_proposals=3,
                        code_quality_signal=code_quality_signal,
                    )
                    async for event in flow.run():
                        if hasattr(event, "message") and event.message:
                            logger.info("Self-Harness [%s]: %s", model_id, event.message)

                    await trajectory_repo.close()
                    logger.info("Self-Harness evolution complete for %s", model_id)

                logger.info("Self-Harness weekly evolution complete (all models)")
            except Exception as exc:
                logger.error("Self-Harness weekly failed: %s", exc, exc_info=True)

        mgr.register_callable("self_harness_evolve", self_harness_evolve)

        await mgr.load_from_config()
        await mgr.start()
