"""Typed configuration for PlanActFlow — replaces the 22-parameter constructor.

Grouped into logical sub-sections so that DI call sites pass a single typed
object instead of a long positional/keyword argument list.

Usage::

    config = PlanActFlowConfig(
        llm=container.get(LLMPort),
        tools=tool_collection,
        session=session,
        state_repo=container.get(StateRepositoryPort),
        event_bus=container.get(EventBusPort),
    )
    flow = PlanActFlow(config)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import DEFAULT_MAX_FLOW_ITERATIONS, DEFAULT_MAX_STEP_REPETITIONS

logger = logging.getLogger(__name__)
from weebot.core.structured_logger import StructuredLogger
from weebot.domain.models.session import Session
from weebot.domain.models.task_preset import TaskPreset


@dataclass
class PlanActFlowConfig:
    """All configuration for a :class:`~weebot.application.flows.plan_act_flow.PlanActFlow`.

    Every field that was previously a constructor argument is represented here
    with the same default, so migrating a call site is a mechanical translation.
    """

    # ── Core (required) ─────────────────────────────────────────────
    llm: LLMPort
    """Language model adapter used by PlannerAgent and ExecutorAgent."""

    tools: ToolCollection | None
    """Tool collection for the executor.  May be ``None`` in SkillOpt mode."""

    session: Session
    """The session this flow operates on."""

    # ── Infrastructure ports (optional, wired by DI) ────────────────
    event_bus: EventBusPort | None = None
    mediator: Any | None = None  # Mediator (avoids circular import)
    state_repo: Any | None = None  # StateRepositoryPort
    checkpoint_port: Any | None = None  # CheckpointPort
    steering: Any | None = None  # SteeringPort — mid-execution user feedback (Phase 5)
    tracing_port: Any | None = None  # TracingPort — OTEL distributed tracing (ARCH-AUDIT-V2 B2)

    # ── Execution limits ────────────────────────────────────────────
    max_step_repetitions: int = DEFAULT_MAX_STEP_REPETITIONS
    max_iterations: int = DEFAULT_MAX_FLOW_ITERATIONS
    max_steps: int | None = None
    auto_terminate_on_plan_complete: bool = True
    termination_conditions: list | None = None  # list[TerminationCondition]
    planning_mode: str = "auto"  # "sequential", "dppm", or "auto" (dppm for complex tasks)

    # ── Critique & validation ───────────────────────────────────────
    truth_binder: Any | None = None  # TruthBinder
    plan_critic: Any | None = None  # PlanCriticService
    code_reviewer: Any | None = None  # CodeReviewerPort — per-step code review
    step_evaluator: Any | None = None  # StepEvaluatorPort — per-step progress evaluation

    # ── Learning & memory ───────────────────────────────────────────
    episodic_memory: Any | None = None
    behavioral_learner: Any | None = None
    knowledge_graph: Any | None = None
    skill_prompt: str | None = None
    skill_retriever: Any | None = None  # SkillRetrieverPort — Tier 1.2
    skill_distiller: Any | None = None  # AutonomousSkillCreator — Phase 1 distillation
    skill_review_gate: Any | None = None  # SkillReviewGate — promotes quarantined -> candidate

    # ── Identity ────────────────────────────────────────────────────
    model: str | None = None
    profile_name: str | None = None  # SOUL.md profile (e.g. "coder", "researcher")
    agent_role: str | None = None  # Agent role for per-role model selection
    personality: Any | None = None  # PersonalityManager
    context_aware_model_selection: bool = True

    # ── LongHorizon-Harness E1: per-step evidence audit ──────────────
    step_audit_service: Any | None = None  # StepAuditPort
    """Optional environment-grounded evidence check run before a step is
    marked COMPLETED. If None, ExecutingState skips the gate (backward-
    compatible)."""

    # ── LongHorizon-Harness E6: verifier cascade tier ────────────────
    verifier_llm: LLMPort | None = None
    """Optional LLM used by VerifyingState instead of the flow's default
    model — routes CoVe/self-critique calls onto ROLE_MODEL_CONFIG's cheap
    "verifier" tier. If None, VerifyingState falls back to ``llm``
    (backward-compatible)."""

    # ── LongHorizon-Harness E7b: workspace integrity axis ────────────
    workspace_snapshots: Any | None = None  # WorkspaceSnapshotPort
    """Optional workspace drift detector wrapped around the verification
    episode. Catches verification writing to the workspace it audits. If
    None, the guard records NOT_RUN — never a pass (backward-compatible)."""

    # ── Enhancement 4: Trust report ─────────────────────────────────
    trust_report_service: Any | None = None  # TrustReportPort

    # ── Enhancement 5: Retention agent ─────────────────────────────
    retention_agent: Any | None = None  # RetentionAgentPort

    # ── Misalignment journal ─────────────────────────────────────────
    misalignment_journal: Any | None = None  # MisalignmentJournalPort
    """Service computing TrustReport from code review + CoVe evidence."""

    # ── ICM edit-source tracking ─────────────────────────────────────
    correction_tracker: Any | None = None  # CorrectionTracker
    """Tracks recurring step-output corrections; surfaces patterns to BehavioralLearner."""

    # ── Lost-in-Compaction: session-scoped side-constraint registry ──
    session_constraint_extractor: Any | None = None  # SessionConstraintExtractor
    """Extracts user-issued side constraints from each turn's prompt so they
    survive compaction. See weebot.domain.models.session_constraint and
    tasks/specs/side_constraint_integrity_plan.md. None disables extraction
    (backward-compatible)."""

    # ── Phase 5: Task preset (cost/quality tier) ────────────────────
    task_preset: TaskPreset | None = None
    """Optional task preset controlling quality gates and model selection.
    If None, flow uses its hardcoded defaults (backward-compatible)."""

    # ── Self-Harness: behavioural harness configuration ─────────────
    harness_config: Any | None = None  # HarnessConfig
    """Optional behavioural harness config (``HarnessConfig`` from
    ``weebot.config.harness.schema``).  When set, the executor's system
    prompt is augmented with instruction blocks from this config.
    When None, behaviour is unchanged (backward-compatible)."""

    # ── Cross-cutting ───────────────────────────────────────────────
    logger: StructuredLogger | None = None
    hooks: Any | None = None  # HookRegistryPort
    """Optional hook registry for PlanActFlow lifecycle callbacks.

    Pass any object satisfying ``weebot.application.ports.hook_registry_port.HookRegistryPort``
    (e.g. ``weebot.templates.hooks.HookRegistry``).  Typed as ``Optional[Any]`` to avoid
    importing the templates layer into the application models module."""

    middleware_chain: Any | None = None  # MiddlewareChain — interceptor pipeline for LLM calls
    """Optional middleware chain wrapping every executor LLM request."""

    event_pipeline: Any | None = None  # EventPipeline — processes events in _emit()
    """Optional event middleware pipeline (EventPipeline).
    When set, ``_emit()`` delegates to the pipeline; when None,
    the legacy inline implementation is used (backward-compatible)."""

    # ── Enhancement H1: Scoped MCP tool aggregation ─────────────────
    tool_registry: Any | None = None  # RoleBasedToolRegistry
    """Shared registry instance.  When ``mcp_bridge`` is also supplied,
    the flow scopes the registry to the current prompt before each turn."""

    mcp_bridge: Any | None = None  # MCPToolRegistryBridge
    """MCP bridge used to scope external tools per query."""

    native_tool_selector: Any | None = None  # NativeToolRetrievalService
    """Optional native-tool selector.  When ``mcp_scope_native_tools`` is
    enabled, this service scopes the native tool set alongside external
    MCP tools so the total per-turn count stays within budget."""

    def __post_init__(self):
        """Auto-select per-model harness if harness_config is None and model is set."""
        if self.harness_config is None and self.model:
            try:
                from weebot.config.model_refs import get_harness_for_model

                harness_path = get_harness_for_model(self.model)
                # Only import if a per-model variant exists (get_harness_for_model
                # returns the default path if no per-model file exists, which means
                # we'd load the default harness — that's fine, it's just redundant)
                if "/models/" in harness_path:  # Per-model variant exists
                    from weebot.config.harness.schema import HarnessConfig

                    self.harness_config = HarnessConfig.load(harness_path)
            except Exception as exc:
                # Graceful fallback — use default harness, but don't hide why.
                logger.warning(
                    "Per-model harness load failed for model=%r — falling back "
                    "to default harness: %s",
                    self.model,
                    exc,
                )
