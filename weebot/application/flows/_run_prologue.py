"""The once-per-run prologue of ``PlanActFlow._run_states`` (debt D4).

Everything before the state loop: open the run span, remember the first substantive
prompt, extract the turn's side constraints, hydrate the behavioural rules, scope the
tools to the query, route to the initial state and run the ``pre_execute`` hooks. It runs
once per turn, so the loop body in ``plan_act_flow.py`` reads as the loop.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from weebot.application.flows.collaborators.tool_assembler import ToolAssembler
from weebot.application.flows.flow_router import FlowRouter
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.planning import PlanningState
from weebot.domain.services.continuation_detector import ContinuationDetector

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow

logger = logging.getLogger(__name__)


async def begin_run(flow: PlanActFlow, prompt: str) -> str:
    """Set the run up and route it; returns the effective prompt for the first state."""
    import time as _time

    flow._flow_started_at = _time.monotonic()
    flow._log.info(f"PlanActFlow started for session {flow._session.id}")

    # ── OTEL tracing: plan_act_iteration span ────────────────────
    # ARCH-AUDIT-V2 B2 — root span for the full Plan-Act-Reflect loop.
    # Uses start_span (not start_as_current_span) because the generator
    # body makes context-manager teardown unreliable.  The span is
    # ended explicitly at the method's exit point below.
    # Gated on WEEBOT_OTEL_TRACING=true (default OFF).
    flow._run_span = None
    if flow._tracing_port is not None:
        from weebot.config.feature_flags import is_enabled

        if is_enabled("OTEL_TRACING_ENABLED"):
            flow._run_span = flow._tracing_port.start_span("plan_act_iteration")
            flow._run_span.set_attribute("session.id", flow._session.id)
            trace_id = getattr(flow._session, "trace_id", None)
            if trace_id:
                flow._run_span.set_attribute("trace_id", trace_id)
    # Store the first substantive prompt so short follow-ups ("proceed", "yes")
    # can be enriched with it when a brand-new plan is needed.
    original_task: str = flow._session.context.get("_original_task", "")
    if not original_task and prompt.strip():
        original_task = prompt.strip()
        flow._session = flow._session.model_copy(
            update={
                "context": flow._session.context.model_copy(
                    update={"original_task": original_task}
                )
            }
        )

    # ── Lost-in-Compaction: extract session-scoped side constraints ──
    # Flow-entry seam — covers every real user turn (initial task,
    # resume, chat) since run() is invoked once per turn. Steering and
    # product-gate resume text are separate seams (Phase 3 follow-up).
    if flow._sc_extractor is not None and prompt.strip():
        await flow._extract_session_constraints(prompt)
    # ──────────────────────────────────────────────────────────────

    # Load durable behavioral rules once per flow. hydrate() is
    # idempotent and flow-guarding; this is the only async seam that
    # runs before the executor builds its system prompt.
    if flow._behavioral_learner is not None:
        try:
            await flow._behavioral_learner.hydrate()
        except Exception as exc:
            logger.warning("Behavioral rule hydration failed: %s", exc)

    # Resolve effective prompt — enrich vague continuations via service
    effective_prompt = ContinuationDetector.resolve_prompt(
        user_prompt=prompt, original_task=original_task, event_count=len(flow._session.events)
    )

    # ── Enhancement H1: scope external MCP tools to the current query ────
    if not hasattr(flow, "_tool_assembler"):
        flow._tool_assembler = ToolAssembler(
            registry=flow._tool_registry,
            mcp_bridge=flow._mcp_bridge,
            native_tool_selector=flow._native_tool_selector,
            llm=flow._llm,
            agent_role=flow._agent_role or "admin",
            logger=flow._stdlib_logger,
        )
    flow._tools = await flow._tool_assembler.assemble(
        effective_prompt=effective_prompt, tools=flow._tools, executor=flow._summary_executor
    )

    # ── Resolve initial state via FlowRouter ───────────────────────────
    initial_state, flow._session = FlowRouter.resolve_initial_state(
        session=flow._session,
        prompt=prompt,
        extra=flow._session.context.extra if flow._session.context else {},
    )
    if isinstance(initial_state, ExecutingState):
        # The step handler reloads the plan from the repo, so routing's
        # changes (an edited plan file, ICM B2) must be saved first.
        if flow._state_repo is not None:
            await flow._state_repo.save_session(flow._session)
        last_plan = flow._session.get_last_plan()
        flow._plan = last_plan
        flow.set_state(initial_state)
    elif isinstance(initial_state, PlanningState):
        # Record misalignment if user rejected the plan, then re-plan
        was_rejected = (
            flow._session.context.extra.get("_plan_modification_request")
            if flow._session.context and flow._session.context.extra
            else None
        )
        if was_rejected and flow._misalignment_journal is not None:
            await FlowRouter.record_misalignment(
                session=flow._session, prompt=was_rejected, journal=flow._misalignment_journal
            )
        flow._plan = None

        # ── Product-mode gate: inject ProductGateState before planning ──
        from weebot.config.feature_flags import PRODUCT_MODE_ENABLED

        if PRODUCT_MODE_ENABLED:
            from weebot.application.flows.states.product_gate import ProductGateState

            flow.set_state(ProductGateState())
        else:
            flow.set_state(initial_state)
    else:
        flow.set_state(initial_state)
    # ────────────────────────────────────────────────────────────────────

    if flow._hooks is not None:
        await flow._hooks.execute_hooks(
            "pre_execute",
            {"session_id": flow._session.id, "prompt": effective_prompt, "plan": None},
        )

    return effective_prompt
