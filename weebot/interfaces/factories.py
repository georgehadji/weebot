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

from weebot.application.flows.flow_builder import build_flow
from weebot.application.flows.base_flow import BaseFlow
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.services.tool_registry import RoleBasedToolRegistry
from weebot.domain.models.base_tool import BaseTool
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.domain.models.session import Session
from weebot.domain.models.task_route import TaskRoute


def _get_tool_collection_cls():
    return ToolCollection


_log = logging.getLogger(__name__)

# Shared DI container — initialized once and cached for all flow creation.
import threading

_shared_container = None
_shared_container_lock = threading.Lock()


def _cached(key: str):
    """Resolve a DI service by key, caching the container across calls.

    Thread-safe: uses a lock for container initialization.
    """
    try:
        return shared_container().get(key)
    except Exception:
        return None


def shared_container():
    """The process's one DI container, built on first use (W5.3).

    Entry points use this rather than building their own, so a `flow run`
    configures the object graph once. Unlike ``_cached`` it raises when the
    container cannot be built.
    """
    global _shared_container
    if _shared_container is None:
        with _shared_container_lock:
            if _shared_container is None:
                from weebot.application.di import Container

                container = Container()
                container.configure_defaults()
                _shared_container = container
    return _shared_container


def reset_shared_container() -> None:
    """Forget the shared container so the next ``shared_container()`` builds a new one.

    Owner of the singleton is this module; the reset is for tests and for a process that
    re-reads its configuration. It does not close what the old container opened.
    """
    global _shared_container
    with _shared_container_lock:
        _shared_container = None


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


async def close_mcp_toolkit() -> None:
    """Close the configured MCP connections, in the task that is ending.

    Left open, asyncio finalised the streamable-HTTP client at loop shutdown
    from another task: "Attempted to exit cancel scope in a different task".
    """
    global _MCP_TOOLKIT
    toolkit, _MCP_TOOLKIT = _MCP_TOOLKIT, None
    if toolkit is None:
        return
    try:
        await toolkit.cleanup()
    except Exception as exc:
        _log.warning("Closing the configured MCP servers failed: %s", exc)


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
    """Factory for creating agent flows (the assembly lives in ``flow_builder.build_flow``).

    Resolves optional services from the process's shared container.
    """
    return build_flow(
        _cached,
        flow_type=flow_type,
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
                persistence_adapter=_cached("session_persistence"),
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

    # The container's registry carries its tool wiring (state repo, reranker,
    # tool config, per-tool collaborators); a bare one would build tools without.
    registry = _cached("tool_registry") or RoleBasedToolRegistry()

    if llm_port is None:
        # Web sessions, the webhook and the gateways pass none; without it the
        # sub-agent tools get no flow factory and fail when called (F48).
        from weebot.application.ports.llm_port import LLMPort as _LLMPort

        llm_port = _cached(_LLMPort)
    # Build flow_factory for tools that spawn sub-agents (debate, dispatch_parallel_tasks)
    flow_factory = _get_flow_factory(llm_port)

    combined: list[BaseTool] = list(
        registry.create_tool_collection(
            role,
            llm_port=llm_port,
            flow_factory=flow_factory,
        )
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
