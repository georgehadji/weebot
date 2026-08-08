"""CQRS handler for validating skills on held-out tasks.

Uses the same TaskRunner-based execution infrastructure to evaluate
the candidate skill against the current best skill.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult
from weebot.application.cqrs.commands.validation_commands import ValidateSkillCommand

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
        skill_store: Optional["SkillStorePort"] = None,
    ):
        self._runner = validation_runner
        self._skill_store = skill_store

    async def handle(self, command: ValidateSkillCommand) -> CommandResult:
        try:
            result = await self._runner.validate(
                candidate_content=command.candidate_content,
                validation_task_ids=list(command.validation_task_ids),
                harness=command.harness,
            )

            if result.passed:
                await self._record_positive_use(command.skill_name)

            return CommandResult.ok(data=result)
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="VALIDATION_ERROR"
            )

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
                    "store — cannot record positive use", skill_name,
                )
                return
            prev_trust = skill.metadata.trust
            updated = skill.record_positive_use(
                promotion_threshold=CANDIDATE_PROMOTION_USES,
            )
            await self._skill_store.save(updated)
            if updated.metadata.trust != prev_trust:
                logger.info(
                    "Skill '%s' promoted %s -> %s (positive_uses=%d)",
                    skill_name, prev_trust, updated.metadata.trust,
                    updated.metadata.provenance.positive_uses,
                )
        except Exception as exc:
            logger.warning(
                "Failed to record positive use for skill '%s': %s",
                skill_name, exc,
            )
