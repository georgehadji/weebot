"""CQRS commands for harness edit operations (Pydantic models).

Commands:
  - ApplyHarnessEditsCommand: validate and apply bounded edits to HarnessConfig.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from weebot.application.cqrs.base import Command


class ApplyHarnessEditsCommand(Command):
    """Validate and apply bounded edits to the active HarnessConfig.

    The edits are first validated via the RegressionGate (Phase 4).
    If they pass, the harness YAML is updated and version is bumped.
    """
    edits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of edit dicts with 'target', 'value', 'mechanism' keys",
    )
    harness_version: str = Field(
        default="",
        description="Base harness version to apply edits to (empty = use loaded)",
    )
    validation_tasks: list[str] = Field(
        default_factory=list,
        description="Task IDs for regression testing",
    )

    def validate(self) -> None:
        if not self.edits:
            raise ValueError("At least one edit is required")
        for e in self.edits:
            if "target" not in e or "value" not in e:
                raise ValueError("Each edit must have 'target' and 'value' keys")
