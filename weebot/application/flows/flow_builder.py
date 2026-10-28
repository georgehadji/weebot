"""Build the flow for a session: the one place that knows how a flow is assembled.

Moved out of ``interfaces/factories.py`` (plan 3.7, LAY-2) so the composition root
(``application/di``) can hand out a flow builder without importing the interfaces
layer, which imports it back. The builder takes a ``resolve`` callable (key -> service
or None) instead of reaching for a process-wide container: the interfaces layer passes
its shared-container lookup, the DI container passes itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from weebot.application.di.keys import SESSION_COST_METER
from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.event_store_port import EventStorePort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session
from weebot.domain.models.task_route import TaskRoute

_log = logging.getLogger(__name__)

Resolve = Callable[[Any], Any]


def _build_ponytail_skill_prompt(existing: str | None) -> str | None:
    """Append Ponytail skill instructions when ponytail_mode is active.

    Delegates to the Application-layer helper so CLI and web share the same
    resolution logic.
    """
    from weebot.application.services.ponytail_skill_prompt import build_ponytail_skill_prompt

    # A caller that already applied a mode -- TaskRunner.create_plan_act_factory
    # applies the SESSION's mode -- must not get the global mode appended as a
    # second block. The session's explicit choice wins.
    if existing and "[Ponytail mode:" in existing:
        return existing
    return build_ponytail_skill_prompt(existing)


def _resolve_personality(resolve: Resolve):
    """Resolve PersonalityManager from the shared DI container, or None."""
    personality = resolve("personality")
    if personality is None:
        _log.debug("PersonalityManager not available in DI")
    return personality


def build_flow(
    resolve: Resolve,
    flow_type: str,
    session: Session,
    llm: LLMPort,
    tools: Any,  # ToolCollection
    event_bus: EventBusPort | None = None,
    model: str | None = None,
    skill_prompt: str | None = None,
    mediator=None,
    state_repo: StateRepositoryPort | None = None,
    steering=None,
    task_route: TaskRoute | None = None,
    profile_name: str | None = None,
    max_iterations: int | None = None,
    max_step_repetitions: int | None = None,
) -> BaseFlow:
    """Factory for creating agent flows.

    When *task_route* is provided, it overrides *flow_type*.
    This allows the task router to determine the execution path
    while maintaining backward compatibility with direct callers.

    *profile_name* selects the SOUL.md profile under
    ``~/.weebot/profiles/<name>/SOUL.md``.  When provided, the
    corresponding persona is injected as slot #1 of the system prompt.

    *max_iterations* and *max_step_repetitions* override the plan-act run limits;
    None keeps the flow's defaults.
    """
    if task_route is not None:
        flow_type = task_route.flow_type
    if mediator is None:
        # Gateways and the webhook passed none, and PlanningState cannot plan
        # without one (F43).
        from weebot.application.cqrs.mediator import Mediator

        mediator = resolve(Mediator)
    if event_bus is None:
        # Gateway and webhook flows passed none: no domain events, and the
        # web UI never saw their progress (F56).
        from weebot.application.ports.event_bus_port import EventBusPort

        event_bus = resolve(EventBusPort)

    if flow_type == "plan_act":
        personality = _resolve_personality(resolve)
        # Resolve optional services from DI container (cached per-process)
        _code_reviewer = resolve("code_reviewer")
        _step_audit_service = resolve("step_audit_service")
        _verifier_llm = resolve("verifier_llm")
        # LongHorizon-Harness E7b. Gated on cost, not principle: two workspace
        # scans add ~3s per verification episode, and the verifier provably
        # cannot write today (test_verifier_readonly_tripwire.py). Leaving the
        # port unresolved keeps that cost off the default path entirely — the
        # guard then records NOT_RUN, which is not a pass.
        from weebot.config.feature_flags import WORKSPACE_INTEGRITY_GUARD_ENABLED

        _workspace_snapshots = (
            resolve("workspace_snapshots") if WORKSPACE_INTEGRITY_GUARD_ENABLED else None
        )
        # LongHorizon-Harness E5: map the router's decision to a cost/quality
        # tier. None when no route was computed (direct create_flow callers) —
        # PlanActFlow falls back to its hardcoded defaults.
        _task_preset = None
        if task_route is not None:
            from weebot.config.task_preset_registry import select_preset

            _task_preset = select_preset(task_route)
        # Knowledge-graph extraction is opt-in: the hook in ExecutingState
        # writes a node per "key: value" line of every step result.
        from weebot.config.feature_flags import KNOWLEDGE_GRAPH_EXTRACTION_ENABLED

        _knowledge_graph = (
            resolve("knowledge_graph") if KNOWLEDGE_GRAPH_EXTRACTION_ENABLED else None
        )
        limits = {
            name: value
            for name, value in (
                ("max_iterations", max_iterations),
                ("max_step_repetitions", max_step_repetitions),
            )
            if value is not None
        }
        return PlanActFlow(
            **limits,
            llm=llm,
            tools=tools,
            session=session,
            event_bus=event_bus,
            model=model,
            skill_prompt=_build_ponytail_skill_prompt(skill_prompt),
            mediator=mediator,
            state_repo=state_repo,
            steering=steering,
            profile_name=profile_name,
            personality=personality,
            agent_role=profile_name,  # SOUL.md profile doubles as agent role
            code_reviewer=_code_reviewer,
            step_audit_service=_step_audit_service,
            task_preset=_task_preset,
            verifier_llm=_verifier_llm,
            workspace_snapshots=_workspace_snapshots,
            knowledge_graph=_knowledge_graph,
            # Phase 7: these three had DI bindings but no caller on the
            # user-facing path, so the behavioral-rule loop, the correction
            # tracker, and side-constraint extraction were all inert here.
            behavioral_learner=resolve("behavioral_learner"),
            correction_tracker=resolve("correction_tracker"),
            session_constraint_extractor=resolve("session_constraint_extractor"),
            # For CompletedState's background jobs, which built a whole
            # Container per completion to find these (W5.3, F28).
            idea_gate=resolve("idea_gate"),
            dreamer_agent=resolve("dreamer_agent"),
            event_store=resolve(EventStorePort),
            persistence_adapter=resolve("session_persistence"),
            cost_meter=resolve(SESSION_COST_METER),
            # Lessons and violations that outlive the session, keyed per project.
            misalignment_journal=resolve("misalignment_journal"),
            # Skills distilled from successful runs, then reviewed quarantined -> candidate.
            skill_distiller=resolve("skill_distiller"),
            skill_review_gate=resolve("skill_review_gate"),
            # Failed runs on similar tasks, turned into planner notes.
            trajectory_repo=resolve("trajectory_repo"),
        )
    if flow_type == "chat":
        from weebot.application.flows.chat_flow import ChatFlow

        return ChatFlow(
            llm=llm,
            session=session,
            event_bus=event_bus,
            model=model,
            mediator=mediator,
            state_repo=state_repo,
            persistence_adapter=resolve("session_persistence"),
        )
    raise ValueError(f"Unknown flow type: {flow_type}")
