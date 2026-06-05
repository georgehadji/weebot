"""SkillCurator bindings mixin for Container."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SkillsMixin:
    """SkillCurator + weekly cron job registration."""

    def configure_skill_curator(self):
        self.register("skill_curator", self._create_skill_curator)

    def _create_skill_curator(self):
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.application.services.skill_curator import SkillCurator
        from weebot.application.ports.llm_port import LLMPort
        registry = SkillRegistry()
        llm = self._maybe_get(LLMPort)
        if llm is None:
            raise RuntimeError(
                "LLMPort must be configured before SkillCurator. "
                "Call configure_defaults() before configure_skill_curator()."
            )
        return SkillCurator(registry=registry, llm=llm)

    async def register_curator_job(self, scheduler_db="./weebot_jobs.db"):
        from weebot.scheduling.scheduler import SchedulingManager
        curator = self.get("skill_curator")
        mgr = SchedulingManager(db_path=scheduler_db)
        mgr.register_callable("skill_curation", curator.run_curation)
        existing = await mgr.list_jobs()
        if not any(j.job_id == "weebot-skill-curator-weekly" for j in existing):
            await mgr.create_job(
                job_id="weebot-skill-curator-weekly",
                name="Weekly Skill Curation",
                trigger_type="cron",
                trigger_config={"day_of_week": "sun", "hour": 2, "minute": 0},
                callable_name="skill_curation",
                description="Classify and review stale skills weekly.",
            )
            logger.info("Registered weekly SkillCurator cron job")
        await mgr.start()
