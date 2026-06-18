"""CQRS handlers for all command and query types.

Consolidated registration functions and handler exports.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult, QueryHandler, QueryResult

# ---- Command handlers (split into individual files) ----
from weebot.application.cqrs.handlers.create_plan_handler import CreatePlanHandler
from weebot.application.cqrs.handlers.execute_step_handler import ExecuteStepHandler
from weebot.application.cqrs.handlers.update_plan_handler import UpdatePlanHandler
from weebot.application.cqrs.handlers.cancel_session_handler import CancelSessionHandler
from weebot.application.cqrs.handlers.compact_memory_handler import CompactMemoryHandler
from weebot.application.cqrs.handlers.process_message_handler import ProcessMessageHandler
from weebot.application.cqrs.handlers.summarize_handler import SummarizeHandler
from weebot.application.cqrs.handlers.archive_session_handler import ArchiveSessionHandler

# ---- Specialized handlers ----
from weebot.application.cqrs.handlers.skill_edit_handler import ApplySkillEditsHandler
from weebot.application.cqrs.handlers.validation_handler import ValidateSkillHandler
from weebot.application.cqrs.handlers.transfer_handler import ValidateTransferHandler
from weebot.application.cqrs.handlers.trajectory_handler import (
    ScoreTrajectoryHandler,
    BuildOptimizationBatchHandler,
)
from weebot.application.cqrs.handlers.failure_signature_handlers import (
    BatchExtractSignaturesHandler,
    ClusterFailurePatternsHandler,
    ExtractFailureSignatureHandler,
)

# ---- Query handlers ----
from weebot.application.cqrs.handlers.session_queries import (
    GetSessionHandler,
    GetSessionStatusHandler,
    ListSessionsHandler,
    GetSessionHistoryHandler,
    SearchSessionsHandler,
    GetSimilarSessionsHandler,
)
from weebot.application.cqrs.handlers.plan_queries import (
    GetPlanHandler,
    GetPlanVisualizationHandler,
)
from weebot.application.cqrs.handlers.active_queries import (
    GetActiveTasksHandler,
    GetActiveSessionsHandler,
    GetCostSummaryHandler,
)

from weebot.application.cqrs.commands import (
    ArchiveSessionCommand,
    CancelSessionCommand,
    CompactMemoryCommand,
    CreatePlanCommand,
    ExecuteStepCommand,
    ProcessMessageCommand,
    SummarizeCommand,
    UpdatePlanCommand,
)

from weebot.application.cqrs.commands.skill_edit_commands import ApplySkillEditsCommand
from weebot.application.cqrs.commands.trajectory_commands import (
    BuildOptimizationBatchCommand,
    ScoreTrajectoryCommand,
)
from weebot.application.cqrs.commands.validation_commands import ValidateSkillCommand
from weebot.application.cqrs.commands.transfer_commands import ValidateTransferCommand
from weebot.application.cqrs.commands.failure_signature_commands import (
    BatchExtractSignaturesCommand,
    ClusterFailurePatternsQuery,
    ExtractFailureSignatureCommand,
)
from weebot.application.cqrs.queries import (
    GetSessionQuery,
    GetSessionStatusQuery,
    ListSessionsQuery,
    GetSessionHistoryQuery,
    GetPlanQuery,
    SearchSessionsQuery,
    GetSimilarSessionsQuery,
    GetActiveTasksQuery,
    GetActiveSessionsQuery,
    GetPlanVisualizationQuery,
    GetCostSummaryQuery,
)

from weebot.application.models.tool_collection import ToolCollection


if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.application.ports.skill_store_port import SkillStorePort
    from weebot.application.ports.trajectory_repository_port import TrajectoryRepositoryPort
    from weebot.application.services.task_runner import TaskRunner


# ---- Registration functions ----
def register_default_handlers(
    mediator,
    state_repo: StateRepositoryPort,
    task_runner: TaskRunner = None,
    *,
    llm=None,
    tools=None,
    event_bus=None,
    scoring_port=None,
    trajectory_builder=None,
) -> None:
    """Register all default command and query handlers with a mediator.

    Args:
        mediator: The Mediator instance.
        state_repo: State repository for persistence operations.
        task_runner: Optional task runner for task management.
        llm: LLMPort for agent handlers (required for CreatePlanHandler etc.).
        tools: ToolCollection for execution handler.
        event_bus: Optional EventBusPort for agent event publishing.
        scoring_port: Optional ScoringPort for trajectory scoring (SkillOpt).
        trajectory_builder: Optional TrajectoryBuilder for trajectory creation.
    """
    from weebot.application.cqrs.mediator import Mediator

    if not isinstance(mediator, Mediator):
        raise ValueError("mediator must be a Mediator instance")

    # --- Command handlers ---
    # Handlers that call agents need llm and tools; fall back to validation-only
    # if these aren't provided (legacy compatibility).
    if llm is not None:
        mediator.register_command_handler(
            CreatePlanCommand,
            CreatePlanHandler(state_repo, llm, event_bus),
        )
        mediator.register_command_handler(
            ProcessMessageCommand,
            ProcessMessageHandler(state_repo, llm),
        )
        mediator.register_command_handler(
            ExecuteStepCommand,
            ExecuteStepHandler(state_repo, llm, tools or _empty_tools(), event_bus),
        )
        mediator.register_command_handler(
            UpdatePlanCommand,
            UpdatePlanHandler(state_repo, llm, event_bus),
        )
    else:
        mediator.register_command_handler(
            CreatePlanCommand, CreatePlanHandler(state_repo)
        )
        mediator.register_command_handler(
            ExecuteStepCommand, ExecuteStepHandler(state_repo)
        )
        mediator.register_command_handler(
            UpdatePlanCommand, UpdatePlanHandler(state_repo)
        )
    mediator.register_command_handler(
        CompactMemoryCommand, CompactMemoryHandler(state_repo)
    )
    mediator.register_command_handler(
        ArchiveSessionCommand, ArchiveSessionHandler(state_repo)
    )
    if llm is not None:
        mediator.register_command_handler(
            SummarizeCommand, SummarizeHandler(llm, state_repo)
        )

    if task_runner:
        mediator.register_command_handler(
            CancelSessionCommand, CancelSessionHandler(task_runner)
        )

    # --- Optional: trajectory scoring (SkillOpt-aware) ---
    if scoring_port is not None and trajectory_builder is not None:
        mediator.register_command_handler(
            ScoreTrajectoryCommand,
            ScoreTrajectoryHandler(scoring_port, state_repo, trajectory_builder),
        )

    # --- Query handlers ---
    mediator.register_query_handler(
        GetSessionQuery, GetSessionHandler(state_repo)
    )
    mediator.register_query_handler(
        ListSessionsQuery, ListSessionsHandler(state_repo)
    )
    mediator.register_query_handler(
        GetSessionStatusQuery,
        GetSessionStatusHandler(state_repo, task_runner),
    )
    mediator.register_query_handler(
        GetSessionHistoryQuery, GetSessionHistoryHandler(state_repo)
    )
    mediator.register_query_handler(
        GetPlanQuery, GetPlanHandler(state_repo)
    )
    mediator.register_query_handler(
        SearchSessionsQuery, SearchSessionsHandler(state_repo)
    )
    mediator.register_query_handler(
        GetSimilarSessionsQuery, GetSimilarSessionsHandler(state_repo)
    )
    if task_runner is None:
        # Runtime import — TaskRunner is only imported under TYPE_CHECKING above,
        # so referencing it here without this import raises NameError.
        from weebot.application.services.task_runner import TaskRunner as _TaskRunner
        task_runner = _TaskRunner(state_repo=state_repo)
    mediator.register_query_handler(
        GetActiveTasksQuery,
        GetActiveTasksHandler(task_runner),
    )

    # ── Operations Console queries (Enhancement 4) ──────────────────
    mediator.register_query_handler(
        GetActiveSessionsQuery,
        GetActiveSessionsHandler(state_repo),
    )
    mediator.register_query_handler(
        GetPlanVisualizationQuery,
        GetPlanVisualizationHandler(state_repo),
    )
    mediator.register_query_handler(
        GetCostSummaryQuery,
        GetCostSummaryHandler(state_repo),
    )


def register_skillopt_handlers(
    mediator,
    *,
    scoring_port,
    state_repo,
    trajectory_builder,
    skill_store,
    trajectory_repo,
    validation_runner,
    flow_factory,
    llm_port=None,
) -> None:
    """Register SkillOpt-specific command handlers with a mediator.

    These handlers are NOT registered by default — they require SkillOpt
    infrastructure dependencies (SkillStore, TrajectoryRepository, etc.).
    Call this after ``register_default_handlers()`` to add them.

    Args:
        mediator: The Mediator instance.
        scoring_port: ScoringPort for trajectory evaluation.
        state_repo: StateRepositoryPort for session persistence.
        trajectory_builder: TrajectoryBuilder for trajectory creation.
        skill_store: SkillStore for skill persistence.
        trajectory_repo: TrajectoryRepository for trajectory storage.
        validation_runner: ValidationRunner for skill validation.
        flow_factory: Flow factory callable for transfer validation.
    """
    from weebot.application.cqrs.mediator import Mediator

    if not isinstance(mediator, Mediator):
        raise ValueError("mediator must be a Mediator instance")

    # ScoreTrajectoryCommand — also callable from register_default_handlers()
    # when scoring deps are available; this ensures it's always registered
    # when SkillOpt is configured.  The mediator is passed so the handler
    # can emit ExtractFailureSignatureCommand on failed trajectories.
    mediator.register_command_handler(
        ScoreTrajectoryCommand,
        ScoreTrajectoryHandler(
            scoring_port, state_repo, trajectory_builder, mediator=mediator,
        ),
    )

    # Skill edits (from optimizer reflection → merge → rank pipeline)
    mediator.register_command_handler(
        ApplySkillEditsCommand,
        ApplySkillEditsHandler(skill_store),
    )

    # Build optimization batches from collected trajectories
    mediator.register_command_handler(
        BuildOptimizationBatchCommand,
        BuildOptimizationBatchHandler(trajectory_repo),
    )

    # Validate candidate skills on held-out tasks
    mediator.register_command_handler(
        ValidateSkillCommand,
        ValidateSkillHandler(validation_runner),
    )

    # Cross-model transfer validation
    mediator.register_command_handler(
        ValidateTransferCommand,
        ValidateTransferHandler(state_repo, skill_store, flow_factory),
    )

    # ── Self-Harness: failure signature extraction on failed trajectories ──
    _fs_handler = ExtractFailureSignatureHandler(
        llm=llm_port,
        trajectory_repo=trajectory_repo,
        budget_model=None,  # Use default budget model
    )
    mediator.register_command_handler(
        ExtractFailureSignatureCommand,
        _fs_handler,
    )

    # ── Self-Harness: batch re-extraction for bootstrapping ───────────────
    mediator.register_command_handler(
        BatchExtractSignaturesCommand,
        BatchExtractSignaturesHandler(
            handler=_fs_handler,
            trajectory_repo=trajectory_repo,
        ),
    )

    # ── Self-Harness: cluster failure patterns for harness proposal ──────
    mediator.register_query_handler(
        ClusterFailurePatternsQuery,
        ClusterFailurePatternsHandler(trajectory_repo),
    )
