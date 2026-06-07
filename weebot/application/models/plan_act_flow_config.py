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

    # ── Critique & validation ───────────────────────────────────────
    truth_binder: Optional[Any] = None  # TruthBinder
    plan_critic: Optional[Any] = None  # PlanCriticService

    # ── Learning & memory ───────────────────────────────────────────
    episodic_memory: Optional[Any] = None
    behavioral_learner: Optional[Any] = None
    knowledge_graph: Optional[Any] = None
    skill_prompt: Optional[str] = None

    # ── Identity ────────────────────────────────────────────────────
    model: Optional[str] = None
    profile_name: Optional[str] = None  # SOUL.md profile (e.g. "coder", "researcher")
    agent_role: Optional[str] = None  # Agent role for per-role model selection
    personality: Optional[Any] = None  # PersonalityManager
    context_aware_model_selection: bool = True

    # ── Cross-cutting ───────────────────────────────────────────────
    logger: Optional[StructuredLogger] = None