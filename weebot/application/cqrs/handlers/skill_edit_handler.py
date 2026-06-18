"""CQRS handler for applying skill edits through the validation gate."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from weebot.application.cqrs.base import CommandHandler, CommandResult
from weebot.application.cqrs.commands.skill_edit_commands import ApplySkillEditsCommand
from weebot.domain.models.skill import Skill
from weebot.domain.models.skill_edit import SkillEdit

if TYPE_CHECKING:
    from weebot.application.ports.skill_store_port import SkillStorePort


class ApplySkillEditsHandler(CommandHandler):
    """Apply bounded edits to a skill and produce a candidate version.

    Does NOT persist the candidate — that is the caller's responsibility
    after the validation gate has accepted or rejected it.
    """

    def __init__(self, skill_store: SkillStorePort):
        self._skill_store = skill_store

    async def handle(self, command: ApplySkillEditsCommand) -> CommandResult:
        try:
            skill = await self._skill_store.load(command.skill_name)
            if skill is None:
                return CommandResult.fail(
                    error=f"Skill '{command.skill_name}' not found",
                    error_code="SKILL_NOT_FOUND",
                )

            # Convert dicts to SkillEdit domain objects
            edits = []
            for raw in command.edits:
                edits.append(SkillEdit(
                    op=raw["op"],
                    target=raw.get("target"),
                    content=raw.get("content", ""),
                    support_count=raw.get("support_count", 1),
                    source_type=raw.get("source_type", "failure"),
                ))

            # Apply with budget
            candidate = skill.apply_edits(edits, budget=command.budget)

            return CommandResult.ok(data={
                "skill_name": command.skill_name,
                "original_version": skill.current_version,
                "candidate_version": candidate.current_version,
                "edits_applied": len(edits),
                "budget": command.budget,
                "candidate_content": candidate.content,
                "skill": candidate,
            })
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="SKILL_EDIT_APPLY_ERROR"
            )
