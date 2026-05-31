"""CQRS handler for validating skills on held-out tasks.

Uses the same TaskRunner-based execution infrastructure to evaluate
the candidate skill against the current best skill.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from weebot.application.cqrs.base import CommandHandler, CommandResult
from weebot.application.cqrs.commands.validation_commands import ValidateSkillCommand

if TYPE_CHECKING:
    from weebot.application.services.validation_runner import ValidationRunner


class ValidateSkillHandler(CommandHandler):
    """Validate a candidate skill on held-out tasks.

    The validation runner compares the candidate score against the
    current best score and returns acceptance/rejection.
    """

    def __init__(self, validation_runner: ValidationRunner):
        self._runner = validation_runner

    async def handle(self, command: ValidateSkillCommand) -> CommandResult:
        try:
            result = await self._runner.validate(
                candidate_content=command.candidate_content,
                validation_task_ids=list(command.validation_task_ids),
                harness=command.harness,
            )

            return CommandResult.ok(data=result)
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="VALIDATION_ERROR"
            )
