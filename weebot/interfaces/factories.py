"""Factories for flows and tool collections.

Supports TaskRoute-based flow selection (Enhancement 6 — Neural Task Router).
When a TaskRoute is provided, flow_type is derived from the route rather
than being passed explicitly.

SOUL.md identity is resolved from the DI container and injected into
PlanActFlow.  The ``profile_name`` parameter maps to the SOUL.md profile
under ``~/.weebot/profiles/<name>/SOUL.md``.
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.domain.models.session import Session
from weebot.domain.models.task_route import TaskRoute


# Lazy import via importlib to avoid import-linter trace
def _get_tool_collection_cls():
    import importlib as _il

    return _il.import_module("weebot.tools.base").ToolCollection


_log = logging.getLogger(__name__)

# Shared DI container — initialized once and cached for all flow creation.
import threading

_shared_container = None
_shared_container_lock = threading.Lock()


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


def _cached(key: str):
    """Resolve a DI service by key, caching the container across calls.

    Thread-safe: uses a lock for container initialization.
    """
    global _shared_container
    if _shared_container is None:
        with _shared_container_lock:
            if _shared_container is None:
                try:
                    from weebot.application.di import Container

                    _shared_container = Container()
                    _shared_container.configure_defaults()
                except Exception:
                    return None
    try:
        return _shared_container.get(key)
    except Exception:
        return None


_MCP_TOOLKIT: Any = None  # MCPToolkitAdapter, connected once per process
_MCP_LOCK: Any = None


def _resolve_mcp_client() -> Any:
    """The DI "mcp_client" (MCPClientManager), logging why when it is missing.

    ``_cached`` swallows errors; a ConfigError here (``${POSTIZ_API_KEY}`` unset)
    must be visible, or the configured server's tools just vanish.
    """
    if _cached("mcp_client") is None and _shared_container is not None:
        try:
            return _shared_container.get("mcp_client")
        except Exception as exc:
            _log.warning("Configured MCP servers not loaded: %s", exc)
            return None
    return _cached("mcp_client")


async def _configured_mcp_tools() -> list:
    """Tools of the servers in MCP_SERVERS_CONFIG_PATH (WEEBOT_ENABLE_X_MCP).

    MCPToolRegistryBridge only adds names to roles and the registry cannot
    build an MCP tool, so this is the path that makes them callable. Connected
    once per process; a failure is logged and the flow runs without them.
    """
    global _MCP_TOOLKIT, _MCP_LOCK
    import asyncio

    if _MCP_TOOLKIT is not None:
        return _MCP_TOOLKIT.get_tools()
    _MCP_LOCK = _MCP_LOCK or asyncio.Lock()
    async with _MCP_LOCK:
        if _MCP_TOOLKIT is not None:
            return _MCP_TOOLKIT.get_tools()
        manager = _resolve_mcp_client()
        if manager is None or not getattr(manager, "has_servers", False):
            return []
        import importlib as _il

        toolkit_cls = _il.import_module(
            "weebot.infrastructure.mcp.mcp_toolkit_adapter"
        ).MCPToolkitAdapter
        toolkit = toolkit_cls(manager)
        try:
            await toolkit.initialize()
        except Exception as exc:
            _log.warning("Configured MCP servers not connected: %s", exc)
            return []
        _MCP_TOOLKIT = toolkit
        _log.info("Configured MCP servers connected: %d tools", len(toolkit.get_tools()))
        return toolkit.get_tools()


async def route_and_create_flow(
    query: str,
    session: Session,
    llm: LLMPort,
    tools: Any,  # ToolCollection — resolved via _get_tool_collection_cls()
    router: TaskRouterPort,
    event_bus: EventBusPort | None = None,
    model: str | None = None,
    skill_prompt: str | None = None,
    mediator=None,
    state_repo: StateRepositoryPort | None = None,
    steering=None,
    profile_name: str | None = None,
) -> tuple[BaseFlow, TaskRoute]:
    """Route *query* through *router*, then create the appropriate flow.

    Returns (flow, route) so callers can inspect the route decision.
    """
    task_route = await router.route(query)
    flow = create_flow(
        flow_type=task_route.flow_type,
        session=session,
        llm=llm,
        tools=tools,
        event_bus=event_bus,
        model=model,
        skill_prompt=skill_prompt,
        mediator=mediator,
        state_repo=state_repo,
        steering=steering,
        task_route=task_route,
        profile_name=profile_name,
    )
    return flow, task_route


def _resolve_personality():
    """Resolve PersonalityManager from the shared DI container, or None."""
    personality = _cached("personality")
    if personality is None:
        _log.debug("PersonalityManager not available in DI")
    return personality


def create_flow(
    flow_type: str,
    session: Session,
    llm: LLMPort,
    tools: Any,  # ToolCollection — resolved via _get_tool_collection_cls()
    event_bus: EventBusPort | None = None,
    model: str | None = None,
    skill_prompt: str | None = None,
    mediator=None,
    state_repo: StateRepositoryPort | None = None,
    steering=None,
    task_route: TaskRoute | None = None,
    profile_name: str | None = None,
) -> BaseFlow:
    """Factory for creating agent flows.

    When *task_route* is provided, it overrides *flow_type*.
    This allows the task router to determine the execution path
    while maintaining backward compatibility with direct callers.

    *profile_name* selects the SOUL.md profile under
    ``~/.weebot/profiles/<name>/SOUL.md``.  When provided, the
    corresponding persona is injected as slot #1 of the system prompt.
    """
    if task_route is not None:
        flow_type = task_route.flow_type

    if flow_type == "plan_act":
        personality = _resolve_personality()
        # Resolve optional services from DI container (cached per-process)
        _code_reviewer = _cached("code_reviewer")
        _step_audit_service = _cached("step_audit_service")
        _verifier_llm = _cached("verifier_llm")
        # LongHorizon-Harness E7b. Gated on cost, not principle: two workspace
        # scans add ~3s per verification episode, and the verifier provably
        # cannot write today (test_verifier_readonly_tripwire.py). Leaving the
        # port unresolved keeps that cost off the default path entirely — the
        # guard then records NOT_RUN, which is not a pass.
        from weebot.config.feature_flags import WORKSPACE_INTEGRITY_GUARD_ENABLED

        _workspace_snapshots = (
            _cached("workspace_snapshots") if WORKSPACE_INTEGRITY_GUARD_ENABLED else None
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
            _cached("knowledge_graph") if KNOWLEDGE_GRAPH_EXTRACTION_ENABLED else None
        )
        return PlanActFlow(
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
            behavioral_learner=_cached("behavioral_learner"),
            correction_tracker=_cached("correction_tracker"),
            session_constraint_extractor=_cached("session_constraint_extractor"),
        )
    if flow_type == "chat":
        import importlib as _il

        _chat_flow_mod = _il.import_module("weebot.application.flows.chat_flow")
        ChatFlow = _chat_flow_mod.ChatFlow
        return ChatFlow(
            llm=llm, session=session, event_bus=event_bus, model=model, mediator=mediator
        )
    raise ValueError(f"Unknown flow type: {flow_type}")


def _get_flow_factory(llm_port: LLMPort | None) -> Any | None:
    """Build a flow_factory for tools that spawn sub-agent PlanActFlows.

    Returns ``None`` when LLM port is unavailable or Container wiring fails.
    """
    if llm_port is None:
        return None
    try:
        from weebot.application.ports.event_bus_port import EventBusPort
        from weebot.application.ports.state_repo_port import StateRepositoryPort

        # The shared container: a container built here had its own event bus,
        # so sub-agent flows published where nobody listened (F28).
        state_repo = _cached(StateRepositoryPort)
        event_bus = _cached(EventBusPort)
        if state_repo is None or event_bus is None:
            return None

        def _factory(session):
            from weebot.application.flows.plan_act_flow import PlanActFlow
            from weebot.application.models.plan_act_flow_config import PlanActFlowConfig

            config = PlanActFlowConfig(
                llm=llm_port,
                tools=None,
                session=session,
                event_bus=event_bus,
                state_repo=state_repo,
            )
            return PlanActFlow(config=config)

        return _factory
    except Exception:
        return None


async def build_tools(
    role: str = "admin",
    mcp_config: dict | None = None,
    extra_tools: list | None = None,
    llm_port: LLMPort | None = None,
    mcp_adapter: object | None = None,
) -> Any:  # ToolCollection — resolved via _get_tool_collection_cls()
    """Factory for building a ToolCollection for a given role and optional MCP config."""
    import importlib as _il

    _tool_registry_mod = _il.import_module("weebot.tools.tool_registry")
    _base_mod = _il.import_module("weebot.tools.base")
    RoleBasedToolRegistry = _tool_registry_mod.RoleBasedToolRegistry
    BaseTool = _base_mod.BaseTool

    registry = RoleBasedToolRegistry()

    # Build flow_factory for tools that spawn sub-agents (debate, dispatch_parallel_tasks)
    flow_factory = _get_flow_factory(llm_port)

    combined: list[BaseTool] = list(
        registry.create_tool_collection(role, llm_port=llm_port, flow_factory=flow_factory)
    )

    if mcp_config:
        if mcp_adapter is not None:
            adapter = mcp_adapter
        else:
            import importlib as _il

            _mcp_mod = _il.import_module("weebot.infrastructure.mcp.mcp_toolkit_adapter")
            adapter = _mcp_mod.MCPToolkitAdapter()
        await adapter.initialize(mcp_config)
        combined.extend(adapter.get_tools())
    else:
        combined.extend(await _configured_mcp_tools())

    if extra_tools:
        combined.extend(extra_tools)

    # Apify preset tools — opt-in via APIFY_API_KEY env var
    import os
    import logging as _logging

    _apify_logger = _logging.getLogger("weebot.interfaces.factories")
    if os.getenv("APIFY_API_KEY"):
        try:
            import importlib as _il

            ApifyService = _il.import_module("weebot.infrastructure.adapters.apify").ApifyService
            _apify_presets = _il.import_module("weebot.tools.apify_presets")
            create_apify_preset_tools = _apify_presets.create_apify_preset_tools
            apify_service = ApifyService()
            await apify_service.initialize()
            combined.extend(create_apify_preset_tools(apify_service))
        except Exception:
            _apify_logger.warning(
                "Apify integration skipped — initialization failed", exc_info=True
            )

    # MCP, extra and Apify tools join after the registry's own guard_tools call,
    # so wrap again: shell tools are already wrapped and skipped; a financial
    # tool from an MCP server is wrapped here (F06). Resolved through DI because
    # this layer may not import tool_guards. Fail closed: no guard, no tools.
    guard_tools = _cached("guard_tools")
    if guard_tools is None:
        raise RuntimeError("tool guard chain unavailable; refusing to build unguarded tools")
    combined = guard_tools(combined, include_egress=False)
    ToolCollection = _get_tool_collection_cls()
    canonicalizer = _build_action_canonicalizer(combined)
    contract_loader = _cached("contract_loader")
    return ToolCollection(*combined, canonicalizer=canonicalizer, contract_loader=contract_loader)


def _build_action_canonicalizer(tools: list) -> Any:
    """Build the Action Canonicalizer (Tier 1.1) for *tools*, or None on failure.

    Resolved via the DI-registered ``build_action_canonicalizer`` factory so
    this interfaces-layer module never imports the infrastructure adapter
    directly (composition root owns that import). Never raises —
    canonicalization is a safety net, not a hard dependency, so a resolution
    failure falls back to no canonicalizer (ToolCollection.execute() already
    tolerates canonicalizer=None).
    """
    try:
        build = _cached("build_action_canonicalizer")
        if build is None:
            return None
        return build(tools)
    except Exception:
        _log.warning("Action Canonicalizer unavailable — skipping", exc_info=True)
        return None
