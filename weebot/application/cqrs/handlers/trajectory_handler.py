"""CQRS handlers for trajectory evidence pipeline."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from weebot.application.cqrs.base import CommandHandler, CommandResult, QueryHandler, QueryResult
from weebot.application.cqrs.commands.trajectory_commands import (
    BuildOptimizationBatchCommand,
    ScoreTrajectoryCommand,
)
from weebot.application.ports.scoring_port import ScoringPort
from weebot.application.services.trajectory_builder import TrajectoryBuilder
from weebot.domain.models.trajectory import OptimizationBatch

if TYPE_CHECKING:
    from weebot.application.ports.event_store_port import EventStorePort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.application.ports.trajectory_repository_port import (
        TrajectoryRepositoryPort,
    )


class ScoreTrajectoryHandler(CommandHandler):
    """Score a completed session and persist the trajectory.

    Delegates to ScoringPort for benchmark-specific scoring logic
    and to TrajectoryBuilder for compact trajectory text generation.

    When the trajectory fails, automatically emits an
    ``ExtractFailureSignatureCommand`` via the optional mediator to
    kick off the Self-Harness Weakness Mining pipeline.
    """

    def __init__(
        self,
        scoring_port: ScoringPort,
        state_repo: StateRepositoryPort,
        trajectory_builder: TrajectoryBuilder,
        mediator: Any | None = None,
    ):
        self._scoring = scoring_port
        self._state_repo = state_repo
        self._builder = trajectory_builder
        self._mediator = mediator

    async def handle(self, command: ScoreTrajectoryCommand) -> CommandResult:
        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            # Score the session via the harness-specific scorer
            scored_event = await self._scoring.score(
                session, expected_answer=command.expected_answer
            )

            # Build a structured TrajectorySummary
            trajectory = await self._builder.build(session, scored_event)

            # Persist via event store port
            event_store = getattr(self, "_event_store", None)
            if event_store is not None:
                await event_store.save_trajectory(trajectory)

            # ── Self-Harness: emit failure signature command on failure ──
            if not trajectory.passed and self._mediator is not None:
                try:
                    from weebot.application.cqrs.commands.failure_signature_commands import (
                        ExtractFailureSignatureCommand,
                    )

                    await self._mediator.send(
                        ExtractFailureSignatureCommand(
                            session_id=command.session_id,
                            task_id=trajectory.task_id,
                            trajectory_text=trajectory.trajectory_text,
                            failure_modes=trajectory.failure_modes,
                            harness_version=trajectory.harness,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to emit failure signature extraction for session %s: %s",
                        command.session_id, exc,
                    )

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "score": scored_event.score,
                    "trajectory": trajectory.model_dump(),
                    "scored_event": scored_event.model_dump(),
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="TRAJECTORY_SCORE_ERROR"
            )

    # Setter for optional event store injection (avoids import at module level)
    def set_event_store(self, store: Any) -> None:
        self._event_store = store


class BuildOptimizationBatchHandler(CommandHandler):
    """Collect trajectories for a skill version into an OptimizationBatch."""

    def __init__(self, trajectory_repo: TrajectoryRepositoryPort):
        self._repo = trajectory_repo

    async def handle(self, command: BuildOptimizationBatchCommand) -> CommandResult:
        try:
            trajectories = await self._repo.get_by_skill(
                skill_name=command.skill_name,
                skill_version=command.skill_version,
                limit=command.batch_size,
            )

            if not trajectories:
                return CommandResult.ok(
                    data={
                        "batch": None,
                        "trajectory_count": 0,
                        "message": f"No trajectories found for skill '{command.skill_name}' v{command.skill_version}",
                    }
                )

            batch = OptimizationBatch(
                skill_name=command.skill_name,
                skill_version=command.skill_version,
                trajectories=trajectories,
                batch_score=sum(t.score for t in trajectories) / len(trajectories),
                failure_count=sum(1 for t in trajectories if not t.passed),
                success_count=sum(1 for t in trajectories if t.passed),
            )

            return CommandResult.ok(
                data={
                    "batch": batch.model_dump(),
                    "trajectory_count": len(trajectories),
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="BATCH_BUILD_ERROR"
            )
