"""CQRS handler for validating skills on held-out tasks.

Uses the same TaskRunner-based execution infrastructure to evaluate
the candidate skill against the current best skill.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from weebot.application.cqrs.base import CommandHandler, CommandResult
from weebot.application.cqrs.commands.validation_commands import (
    RecordSkillUseCommand,
    ValidateSkillCommand,
)

if TYPE_CHECKING:
    from weebot.application.ports.skill_store_port import SkillStorePort
    from weebot.application.services.validation_runner import ValidationRunner

logger = logging.getLogger(__name__)


class ValidateSkillHandler(CommandHandler):
    """Validate a candidate skill on held-out tasks.

    The validation runner compares the candidate score against the
    current best score and returns acceptance/rejection. A pass records
    a positive use on the stored skill (Skill.record_positive_use) and
    saves it back — this is the trigger record_positive_use() otherwise
    has no production caller for. Once positive_uses reaches
    CANDIDATE_PROMOTION_USES, the save promotes candidate -> trusted, and
    if skill_store is a MaterializingSkillStore that save also writes the
    skill to disk and refreshes the live retriever's index.
    """

    def __init__(
        self,
        validation_runner: ValidationRunner,
        skill_store: SkillStorePort | None = None,
        max_promotions_per_run: int | None = None,
    ):
        self._runner = validation_runner
        self._skill_store = skill_store
        if max_promotions_per_run is None:
            from weebot.config.learning import MAX_SKILL_PROMOTIONS_PER_RUN

            max_promotions_per_run = MAX_SKILL_PROMOTIONS_PER_RUN
        self._max_promotions_per_run = max_promotions_per_run
        self._promotions_this_run = 0

    async def handle(self, command: ValidateSkillCommand) -> CommandResult:
        try:
            result = await self._runner.validate(
                candidate_content=command.candidate_content,
                validation_task_ids=list(command.validation_task_ids),
                harness=command.harness,
            )

            if result.passed and _measured(result):
                await self._record_positive_use(command.skill_name)

            return CommandResult.ok(data=result)
        except Exception as exc:
            return CommandResult.fail(error=str(exc), error_code="VALIDATION_ERROR")

    async def _record_positive_use(self, skill_name: str) -> None:
        """Best-effort — a promotion-tracking failure must not fail the
        validation result itself, which is the primary thing this command
        reports on."""
        if self._skill_store is None:
            return
        try:
            from weebot.config.learning import CANDIDATE_PROMOTION_USES

            skill = await self._skill_store.load(skill_name)
            if skill is None:
                logger.warning(
                    "Validation passed for '%s' but it is not in the skill "
                    "store — cannot record positive use",
                    skill_name,
                )
                return
            prev_trust = skill.metadata.trust
            updated = skill.record_positive_use(promotion_threshold=CANDIDATE_PROMOTION_USES)
            if updated.metadata.trust != prev_trust:
                if self._promotions_this_run >= self._max_promotions_per_run:
                    logger.warning(
                        "Skill promotion cap (%d/run) reached — '%s' earned "
                        "promotion %s -> %s but it is being withheld (positive "
                        "use is still recorded)",
                        self._max_promotions_per_run,
                        skill_name,
                        prev_trust,
                        updated.metadata.trust,
                    )
                    withheld_meta = updated.metadata.model_copy(update={"trust": prev_trust})
                    updated = updated.model_copy(update={"metadata": withheld_meta})
                else:
                    self._promotions_this_run += 1
            await self._skill_store.save(updated)
            if updated.metadata.trust != prev_trust:
                logger.info(
                    "Skill '%s' promoted %s -> %s (positive_uses=%d)",
                    skill_name,
                    prev_trust,
                    updated.metadata.trust,
                    updated.metadata.provenance.positive_uses,
                )
        except Exception as exc:
            logger.warning("Failed to record positive use for skill '%s': %s", skill_name, exc)


# A bootstrap run (no baseline) "passes" at any score; count it only at this score.
_BOOTSTRAP_PASS_SCORE = 0.5


def _measured(result) -> bool:
    """A pass that measured something: tasks ran, and a bootstrap run scored well."""
    if getattr(result, "n_tasks", 0) <= 0:
        return False
    if getattr(result, "current_score", 0.0) < 0:  # no baseline
        return getattr(result, "candidate_score", 0.0) >= _BOOTSTRAP_PASS_SCORE
    return True


class RecordSkillUseHandler(CommandHandler):
    """Count a live use of a candidate skill: promote at 3 passes, quarantine at 2 failures.

    Each session counts once per outcome, so one long session cannot promote a skill
    alone. Only candidates change; trusted and unknown skills are left as they are.
    """

    def __init__(
        self, skill_store: SkillStorePort, max_promotions_per_run: int | None = None
    ) -> None:
        from weebot.config.learning import MAX_SKILL_PROMOTIONS_PER_RUN

        self._skill_store = skill_store
        if max_promotions_per_run is None:
            max_promotions_per_run = MAX_SKILL_PROMOTIONS_PER_RUN
        self._max_promotions = max_promotions_per_run
        self._promotions = 0

    async def handle(self, command: RecordSkillUseCommand) -> CommandResult:
        from weebot.config.learning import CANDIDATE_DEMOTION_FAILURES, CANDIDATE_PROMOTION_USES

        try:
            skill = await self._skill_store.load(command.skill_name)
            if skill is None:
                return CommandResult.ok(data={"changed": False})
            updated = skill.record_live_use(
                session_id=command.session_id,
                passed=command.passed,
                promotion_threshold=CANDIDATE_PROMOTION_USES,
                demotion_threshold=CANDIDATE_DEMOTION_FAILURES,
            )
            if updated is None:
                return CommandResult.ok(data={"changed": False})
            if updated.metadata.trust == "trusted":
                if self._promotions >= self._max_promotions:
                    logger.warning(
                        "Skill promotion cap (%d/run) reached; '%s' stays candidate",
                        self._max_promotions,
                        skill.name,
                    )
                    updated = updated.with_trust("candidate")
                else:
                    self._promotions += 1
            await self._skill_store.save(updated)
            if updated.metadata.trust != skill.metadata.trust:
                logger.info(
                    "Skill '%s' %s -> %s after a live use in session %s",
                    skill.name,
                    skill.metadata.trust,
                    updated.metadata.trust,
                    command.session_id[:8],
                )
            return CommandResult.ok(data={"changed": True, "trust": updated.metadata.trust})
        except Exception as exc:
            logger.warning("Could not record a use of skill '%s': %s", command.skill_name, exc)
            return CommandResult.fail(error=str(exc), error_code="SKILL_USE_ERROR")
