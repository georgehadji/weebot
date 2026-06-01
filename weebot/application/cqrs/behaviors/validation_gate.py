"""Validation gate behavior — validates skill edits before acceptance.

Intercepts ApplySkillEditsCommand results and runs the candidate
skill through a validation gate.  If validation fails, the command
result is replaced with a failure.
"""
from __future__ import annotations

from typing import Any, Callable

from weebot.application.cqrs.base import Command, CommandResult, IPipelineBehavior, Query
from weebot.application.cqrs.commands.skill_edit_commands import ApplySkillEditsCommand


class ValidationGateBehavior(IPipelineBehavior):
    """Pipeline behaviour that validates skill edits before acceptance.

    Intercepts ApplySkillEditsCommand results and runs the candidate
    skill through a validation gate.  If validation fails, the command
    result is replaced with a failure.

    Register on the mediator:
        mediator = Mediator()
        mediator.add_pipeline_behavior(ValidationGateBehavior(validation_runner))
    """

    def __init__(self, validation_runner=None):
        """Optional — validation runner can be set later via setter."""
        self._runner = validation_runner

    def set_runner(self, validation_runner) -> None:
        self._runner = validation_runner

    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable[[], Any],
    ) -> Any:
        result = await next_callable()

        # Only gate ApplySkillEditsCommand results — use isinstance
        # instead of string comparison to survive command renames.
        if not isinstance(request, ApplySkillEditsCommand):
            return result

        if self._runner is None:
            return result

        # Extract candidate info from the successful result
        if isinstance(result, CommandResult) and result.success:
            data = result.data or {}
            candidate_content = data.get("candidate_content", "")
            skill_name = data.get("skill_name", "")
            validation_ids = getattr(request, "validation_task_ids", [])

            if not validation_ids:
                # No validation tasks configured — accept unconditionally
                return result

            validation_result = await self._runner.validate(
                candidate_content=candidate_content,
                validation_task_ids=list(validation_ids),
                baseline_score=None,
            )

            if not validation_result.passed:
                return CommandResult.fail(
                    error=(
                        f"Validation gate rejected: "
                        f"Δ={validation_result.score_delta:.3f}, "
                        f"candidate={validation_result.candidate_score:.3f}"
                    ),
                    error_code="VALIDATION_GATE_REJECTED",
                )

        return result
