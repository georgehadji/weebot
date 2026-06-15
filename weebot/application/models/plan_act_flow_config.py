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

from dataclasses import dataclass, field
from typing import Any, Optional

from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import DEFAULT_MAX_FLOW_ITERATIONS, DEFAULT_MAX_STEP_REPETITIONS
from weebot.core.structured_logger import StructuredLogger
from weebot.domain.models.session import Session


@dataclass
class PlanActFlowConfig:
    """All configuration for a :class:`~weebot.application.flows.plan_act_flow.PlanActFlow`.

    Every field that was previously a constructor argument is represented here
    with the same default, so migrating a call site is a mechanical translation.
    """

    # ── Core (required) ─────────────────────────────────────────────
    llm: LLMPort
    """Language model adapter used by PlannerAgent and ExecutorAgent."""

    tools: Optional[ToolCollection]
    """Tool collection for the executor.  May be ``None`` in SkillOpt mode."""

    session: Session
    """The session this flow operates on."""

    # ── Infrastructure ports (optional, wired by DI) ────────────────
    event_bus: Optional[EventBusPort] = None
    mediator: Optional[Any] = None  # Mediator (avoids circular import)
    state_repo: Optional[Any] = None  # StateRepositoryPort
    checkpoint_port: Optional[Any] = None  # CheckpointPort
    steering: Optional[Any] = None  # SteeringPort — mid-execution user feedback (Phase 5)

    # ── Execution limits ────────────────────────────────────────────
    max_step_repetitions: int = DEFAULT_MAX_STEP_REPETITIONS
    max_iterations: int = DEFAULT_MAX_FLOW_ITERATIONS
    max_steps: Optional[int] = None
    auto_terminate_on_plan_complete: bool = True
    termination_conditions: Optional[list] = None  # list[TerminationCondition]

    # ── Critique & validation ───────────────────────────────────────
    truth_binder: Optional[Any] = None  # TruthBinder
    plan_critic: Optional[Any] = None  # PlanCriticService
    code_reviewer: Optional[Any] = None  # CodeReviewerPort — per-step code review
    step_evaluator: Optional[Any] = None  # StepEvaluatorPort — per-step progress evaluation

    # ── Learning & memory ───────────────────────────────────────────
    episodic_memory: Optional[Any] = None
    behavioral_learner: Optional[Any] = None
    knowledge_graph: Optional[Any] = None
    skill_prompt: Optional[str] = None
    skill_retriever: Optional[Any] = None  # SkillRetrieverPort — Tier 1.2
    skill_distiller: Optional[Any] = None  # AutonomousSkillCreator — Phase 1 distillation

    # ── Identity ────────────────────────────────────────────────────
    model: Optional[str] = None
    profile_name: Optional[str] = None  # SOUL.md profile (e.g. "coder", "researcher")
    agent_role: Optional[str] = None  # Agent role for per-role model selection
    personality: Optional[Any] = None  # PersonalityManager
    context_aware_model_selection: bool = True

    # ── Enhancement 4: Trust report ─────────────────────────────────
    trust_report_service: Optional[Any] = None  # TrustReportPort

    # ── Enhancement 5: Retention agent ─────────────────────────────
    retention_agent: Optional[Any] = None  # RetentionAgentPort

    # ── Misalignment journal ─────────────────────────────────────────
    misalignment_journal: Optional[Any] = None  # MisalignmentJournalPort
    """Service computing TrustReport from code review + CoVe evidence."""

    # ── Phase 5: Task preset (cost/quality tier) ────────────────────
    task_preset: Optional[Any] = None  # TaskPreset — avoids domain model import
    """Optional task preset controlling quality gates and model selection.
    If None, flow uses its hardcoded defaults (backward-compatible)."""

    # ── Self-Harness: behavioural harness configuration ─────────────
    harness_config: Optional[Any] = None  # HarnessConfig
    """Optional behavioural harness config (``HarnessConfig`` from
    ``weebot.config.harness.schema``).  When set, the executor's system
    prompt is augmented with instruction blocks from this config.
    When None, behaviour is unchanged (backward-compatible)."""

    # ── Cross-cutting ───────────────────────────────────────────────
    logger: Optional[StructuredLogger] = None
    hooks: Optional[Any] = None  # HookRegistryPort
    """Optional hook registry for PlanActFlow lifecycle callbacks.

    Pass any object satisfying ``weebot.application.ports.hook_registry_port.HookRegistryPort``
    (e.g. ``weebot.templates.hooks.HookRegistry``).  Typed as ``Optional[Any]`` to avoid
    importing the templates layer into the application models module."""

    middleware_chain: Optional[Any] = None  # MiddlewareChain — interceptor pipeline for LLM calls
    """Optional middleware chain wrapping every executor LLM request."""