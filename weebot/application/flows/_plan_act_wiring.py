"""Construction of a `PlanActFlow` from its parameter object.

Extracted from `PlanActFlow.__init__`, which was 234 lines doing three unrelated jobs:
translating legacy loose kwargs into `PlanActFlowConfig`, assigning ~50 ports onto
`self`, and composing the agents the flow drives. Only the third is construction
logic; the first is a table, and the second is a table with `self.` in front of it.

Why a module and not three methods: `plan_act_flow.py` sits at its 999/1000-line
allowlist cap, so anything added there has to come out of somewhere else. These
functions take the flow as their first argument because they are wiring, not
behaviour -- the flow still owns every attribute, and nothing here reads one back.

The legacy path is provably equivalent, not approximately: all 36 legacy keyword names
are `PlanActFlowConfig` fields and every default matches (checked 2026-10-25), so
`PlanActFlowConfig(**legacy_kwargs)` builds the same object as the 89-line explicit
mapping it replaces. That is why `config_from_legacy` can delegate rather than carry a
second copy of the table -- the second copy is what drifts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from weebot.application.flows.collaborators.fact_resolver import FactResolver
from weebot.application.flows.states.base import AgentStatus
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.application.services.context_switcher import ContextSwitcher
from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.application.services.model_aware_harness_resolver import ModelAwareHarnessResolver
from weebot.application.services.plan_history import PlanHistory

# The flow's own module name, for the stdlib logger `__init__` used to create with
# `__name__`. Spelled out so the log channel does not change when this code moves.
_FLOW_LOGGER_NAME = "weebot.application.flows.plan_act_flow"

# The keyword surface `PlanActFlow.__init__` accepted before the parameter object
# existed. Kept as data so the error a caller gets names the real surface, and so the
# list can be checked against the config's fields rather than trusted.
LEGACY_KWARG_NAMES: tuple[str, ...] = (
    "llm",
    "tools",
    "session",
    "event_bus",
    "model",
    "skill_prompt",
    "mediator",
    "state_repo",
    "steering",
    "max_step_repetitions",
    "max_iterations",
    "auto_terminate_on_plan_complete",
    "context_aware_model_selection",
    "max_steps",
    "truth_binder",
    "plan_critic",
    "code_reviewer",
    "step_audit_service",
    "task_preset",
    "verifier_llm",
    "workspace_snapshots",
    "knowledge_graph",
    "idea_gate",
    "dreamer_agent",
    "event_store",
    "behavioral_learner",
    "logger",
    "checkpoint_port",
    "profile_name",
    "personality",
    "agent_role",
    "session_constraint_extractor",
    "correction_tracker",
    "persistence_adapter",
    "cost_meter",
    "misalignment_journal",
    "skill_distiller",
    "skill_review_gate",
    "trajectory_repo",
    "step_evaluator",
)


def config_from_legacy(**legacy: Any) -> PlanActFlowConfig:
    """`PlanActFlowConfig` from the legacy loose keywords.

    Every legacy name is a config field of the same name with the same default, so
    this is the dataclass call it always was: the mapping that used to sit inline in
    `__init__` was a 36-line identity function.

    One difference the identity mapping did not have: `llm` and `tools` are *required*
    by the config and were only defaulted to `None` by the legacy signature. Callers
    rely on that -- `tests/e2e/test_gate_pause_survives_the_seam.py` builds a flow with
    neither, because a paused-flow test needs no model -- so the legacy route keeps its
    old behaviour instead of inheriting the dataclass's stricter one.

    Unknown names are rejected by name rather than by the dataclass's generic message,
    because "PlanActFlow() got an unexpected keyword argument 'llm_port'" tells a
    caller nothing about the 36 names that do work.
    """
    unknown = sorted(set(legacy) - set(LEGACY_KWARG_NAMES))
    if unknown:
        raise TypeError(
            f"PlanActFlow() got unexpected keyword argument(s): {', '.join(unknown)}. "
            "Pass a PlanActFlowConfig as the first argument, or use one of: "
            f"{', '.join(LEGACY_KWARG_NAMES)}"
        )
    legacy.setdefault("llm", None)
    legacy.setdefault("tools", None)
    return PlanActFlowConfig(**legacy)


def wire_ports(flow: Any, cfg: PlanActFlowConfig) -> None:
    """Assign the parameter object's ports onto the flow.

    One table, one direction. The three objects built here rather than assigned
    (fact resolver, compactor, context switcher) are built from ports alone, so they
    belong with the ports they read.
    """
    flow._llm = cfg.llm
    flow._tools = cfg.tools
    flow._session = cfg.session
    flow._event_bus = cfg.event_bus
    flow._model = cfg.model
    flow._mediator = cfg.mediator
    flow._state_repo = cfg.state_repo
    flow._fact_resolver = FactResolver(state_repo=flow._state_repo)
    flow._steering = cfg.steering
    flow._truth_binder = cfg.truth_binder
    flow._plan_critic = cfg.plan_critic
    flow._plan_critique = None  # Set by CritiquingState
    flow._code_reviewer = cfg.code_reviewer
    flow._step_audit_service = cfg.step_audit_service
    flow._verifier_llm = cfg.verifier_llm  # cheap-tier LLM for VerifyingState (E6)
    flow._workspace_snapshots = cfg.workspace_snapshots  # integrity axis (E7b)
    flow._step_evaluator = cfg.step_evaluator  # per-step progress
    flow._retention_agent = cfg.retention_agent  # enhancement 5
    # Post-completion jobs (CompletedState): skill-gap review, dream scan.
    flow._idea_gate = cfg.idea_gate
    flow._dreamer_agent = cfg.dreamer_agent
    flow._event_store = cfg.event_store
    flow._task_preset = cfg.task_preset  # Phase 5: cost/quality tier presets
    flow._knowledge_graph = cfg.knowledge_graph
    flow._behavioral_learner = cfg.behavioral_learner
    flow._checkpoint_port = cfg.checkpoint_port
    flow._hooks = cfg.hooks  # Optional[HookRegistry] -- None = no-op
    flow._misalignment_journal = cfg.misalignment_journal
    flow._trajectory_repo = cfg.trajectory_repo  # past failures on similar tasks
    flow._correction_tracker = cfg.correction_tracker
    flow._sc_extractor = cfg.session_constraint_extractor
    flow._session_constraints = None  # hydrated lazily in run()
    flow._profile_name = cfg.profile_name
    flow._agent_role = cfg.agent_role
    flow._personality = cfg.personality
    flow._logger = cfg.logger
    flow._stdlib_logger = logging.getLogger(_FLOW_LOGGER_NAME)
    flow.status = AgentStatus.IDLE
    flow._state = None  # Will be set in run()
    flow._plan = None
    flow._compactor = MemoryCompactor()
    flow._plan_history = PlanHistory()
    flow._context_switcher = ContextSwitcher(llm=flow._llm, event_bus=flow._event_bus)
    flow._awm = None  # AgentWorkflowMemory -- lazy-init via _get_awm()
    flow._max_step_repetitions = cfg.max_step_repetitions
    flow._planning_mode = getattr(cfg, "planning_mode", "auto")
    flow._auto_terminate_on_plan_complete = cfg.auto_terminate_on_plan_complete
    flow._context_aware_model_selection = cfg.context_aware_model_selection
    flow._max_iterations = cfg.max_iterations
    flow._termination_conditions = cfg.termination_conditions or []
    flow._cost_meter = cfg.cost_meter
    flow._cost_hard_override = cfg.session_cost_hard_usd
    flow._budget_grants = 0  # human approvals past the hard limit, one increment each
    flow._pending_budget_request = None  # the ToolCallApproval a paused flow waits on
    flow._step_execution_counts: dict[str, int] = {}
    flow._emit_lock = asyncio.Lock()
    flow._event_publisher = None  # Lazy-init via _get_event_publisher()

    flow._skill_prompt = cfg.skill_prompt
    flow._skill_distiller = cfg.skill_distiller  # Phase 1 -- None when flag is off
    flow._skill_review_gate = cfg.skill_review_gate  # None when flag is off
    flow._tracing_port = cfg.tracing_port
    flow._persistence_adapter = cfg.persistence_adapter

    # ── Enhancement H1: scoped MCP tool aggregation ─────────────
    flow._tool_registry = cfg.tool_registry
    flow._mcp_bridge = cfg.mcp_bridge
    flow._native_tool_selector = cfg.native_tool_selector

    # ── Self-Harness: behavioural instruction block + resolver ──
    flow._harness_instruction_block: str = ""
    flow._harness_config = cfg.harness_config  # HarnessConfig
    flow._harness_resolver = None

    # ── Timing bookkeeping ────────────────────────────────────
    flow._state_entered_at: float | None = None
    flow._flow_started_at: float = 0.0


def compose_agents(flow: Any, cfg: PlanActFlowConfig) -> None:
    """Build the agents the flow drives, from the ports `wire_ports` assigned."""
    from weebot.application.agents.executor import ExecutorAgent
    from weebot.application.agents.planner import PlannerAgent

    if cfg.harness_config is not None:
        try:
            hc = cfg.harness_config
            flow._harness_resolver = ModelAwareHarnessResolver(base_config=hc)
            flow._harness_instruction_block = HarnessPromptAssembler.assemble(
                instructions=hc.instructions,
                runtime_control=hc.runtime_control,
                subagents=hc.subagents,
                skill_selection=hc.skill_selection,
            )
        except (AttributeError, TypeError, ValueError):
            flow._stdlib_logger.error(
                "Failed to assemble harness instructions -- running without harness block",
                exc_info=True,
            )

    flow._planner = PlannerAgent(
        llm=flow._llm,
        event_bus=flow._event_bus,
        model=flow._model,
        skill_prompt=cfg.skill_prompt,
        facts=cfg.session.get_facts(),
        skill_catalog=flow._build_skill_catalog(cfg.skill_retriever),
    )
    executor_kwargs = dict(
        llm=flow._llm,
        tools=flow._tools,
        event_bus=flow._event_bus,
        model=flow._model,
        skill_prompt=cfg.skill_prompt,
        skill_retriever=cfg.skill_retriever,
        profile_name=cfg.profile_name,
        personality=cfg.personality,
        agent_role=cfg.agent_role,
        # Without this the executor's behavioral_learner param was never fed by the
        # flow, so _prompt_builder's "# Behavioral Rules" block stayed empty even
        # when a learner was configured.
        behavioral_learner=cfg.behavioral_learner,
        harness_instruction_block=(
            flow._harness_instruction_block if flow._harness_instruction_block else None
        ),
        middleware_chain=cfg.middleware_chain,
        state_repo=cfg.state_repo,
        tracing_port=flow._tracing_port,
        trajectory_config=(
            cfg.harness_config.trajectory if cfg.harness_config is not None else None
        ),
    )
    if cfg.max_steps is not None:
        executor_kwargs["max_steps"] = cfg.max_steps
    # Steps run on ExecuteStepHandler's executor, which gets these settings through
    # step_execution_context(); this one serves summarize (ADR-015).
    flow._summary_executor = ExecutorAgent(**executor_kwargs)
    _keys = (
        "skill_prompt",
        "skill_retriever",
        "profile_name",
        "personality",
        "agent_role",
        "behavioral_learner",
        "middleware_chain",
        "trajectory_config",
        "max_steps",
    )
    flow._step_settings = {k: executor_kwargs.get(k) for k in _keys}
    flow._step_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    flow.step_skill_gaps: list = []

    # Enhancement 5: subscribe to SkillGapDetected domain events
    if flow._event_bus is not None and flow._misalignment_journal is not None:
        with contextlib.suppress(Exception):
            flow._event_bus.subscribe_domain(flow._on_skill_gap_detected)
