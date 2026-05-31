"""CQRS commands for trajectory evidence pipeline (Pydantic models)."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from weebot.application.cqrs.base import Command


class ScoreTrajectoryCommand(Command):
    """Score a completed session and persist the trajectory."""
    session_id: str = Field(min_length=1)
    harness: str = "direct_chat"
    expected_answer: str | None = None
    context: dict[str, Any] = {}


class BuildOptimizationBatchCommand(Command):
    """Collect trajectories for a skill version into a batch."""
    skill_name: str = Field(min_length=1)
    skill_version: int = 0
    batch_size: int = 40

    def validate(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
