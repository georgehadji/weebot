"""CQRS handler for ApplyHarnessEditsCommand.

Validates edits against the current HarnessConfig, applies them to a
working copy, and persists via HarnessOptimizationTarget.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from weebot.application.cqrs.base import CommandHandler, CommandResult
from weebot.application.cqrs.commands.harness_edit_commands import (
    ApplyHarnessEditsCommand,
)

if TYPE_CHECKING:
    from weebot.application.services.harness_optimization_target import (
        HarnessOptimizationTarget,
    )

logger = logging.getLogger(__name__)


class ApplyHarnessEditsHandler(CommandHandler):
    """Validate and persist harness edits.

    The handler:
      1. Loads the current harness via HarnessOptimizationTarget
      2. Applies candidate edits in a dry-run (no auto-save)
      3. Returns the resulting candidate for the caller to validate
         (the RegressionGate in Phase 4 will decide promotion)
    """

    def __init__(
        self,
        target: "HarnessOptimizationTarget",
    ) -> None:
        self._target = target

    async def handle(self, command: ApplyHarnessEditsCommand) -> CommandResult:
        try:
            # Ensure target has loaded the current harness
            if self._target._current is None:
                await self._target.load()

            # Apply edits to produce a candidate
            candidate = await self._target.apply_edits(command.edits)

            return CommandResult.ok(data={
                "candidate_version": candidate.version,
                "edits_applied": len(command.edits),
                "candidate": candidate.model_dump(),
            })

        except Exception as exc:
            logger.error("Harness edit application failed: %s", exc, exc_info=True)
            return CommandResult.fail(
                error=str(exc),
                error_code="HARNESS_EDIT_ERROR",
            )
