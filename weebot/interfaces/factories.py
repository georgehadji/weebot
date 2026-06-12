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
from typing import Optional

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.domain.models.session import Session
from weebot.domain.models.task_route import TaskRoute
from weebot.tools.base import ToolCollection

_log = logging.getLogger(__name__)

# Shared DI container — initialized once and cached for all flow creation.
import threading
_shared_container = None
_shared_container_lock = threading.Lock()


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


async def route_and_create_flow(
    query: str,
    session: Session,
    llm: LLMPort,
    tools: ToolCollection,
    router: TaskRouterPort,
    event_bus: Optional[EventBusPort] = None,
    model: Optional[str] = None,
    skill_prompt: Optional[str] = None,
    mediator = None,
    state_repo: Optional[StateRepositoryPort] = None,
    steering = None,
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
        profile_name=profile_name,
    )
    return flow, task_route


def _resolve_personality():
    """Resolve PersonalityManager from the DI container, or None."""
    try:
        from weebot.application.di import Container
        c = Container()
        c.configure_defaults()
        return c.get("personality")
    except Exception:
        _log.debug("PersonalityManager not available in DI", exc_info=True)
        return None


def create_flow(
    flow_type: str,
    session: Session,
    llm: LLMPort,
    tools: ToolCollection,
    event_bus: Optional[EventBusPort] = None,
    model: Optional[str] = None,
    skill_prompt: Optional[str] = None,
    mediator = None,
    state_repo: Optional[StateRepositoryPort] = None,
    steering = None,
    task_route: Optional[TaskRoute] = None,
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
        return PlanActFlow(
            llm=llm,
            tools=tools,
            session=session,
            event_bus=event_bus,
            model=model,
            skill_prompt=skill_prompt,
            mediator=mediator,
            state_repo=state_repo,
            steering=steering,
            profile_name=profile_name,
            personality=personality,
            agent_role=profile_name,  # SOUL.md profile doubles as agent role
            code_reviewer=_code_reviewer,
        )
    if flow_type == "chat":
        from weebot.application.flows.chat_flow import ChatFlow
        return ChatFlow(
            llm=llm,
            session=session,
            event_bus=event_bus,
            model=model,
            mediator=mediator,
        )
    raise ValueError(f"Unknown flow type: {flow_type}")


async def build_tools(
    role: str = "admin",
    mcp_config: Optional[dict] = None,
    extra_tools: Optional[list] = None,
    llm_port: Optional[LLMPort] = None,
    mcp_adapter: Optional[object] = None,
) -> ToolCollection:
    """Factory for building a ToolCollection for a given role and optional MCP config."""
    from weebot.tools.tool_registry import RoleBasedToolRegistry
    from weebot.tools.base import BaseTool

    registry = RoleBasedToolRegistry()
    combined: list[BaseTool] = list(registry.create_tool_collection(role, llm_port=llm_port))

    if mcp_config:
        if mcp_adapter is not None:
            adapter = mcp_adapter
        else:
            from weebot.infrastructure.mcp.mcp_toolkit_adapter import MCPToolkitAdapter
            adapter = MCPToolkitAdapter()
        await adapter.initialize(mcp_config)
        combined.extend(adapter.get_tools())

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
            from weebot.tools.apify_presets import create_apify_preset_tools
            apify_service = ApifyService()
            await apify_service.initialize()
            combined.extend(create_apify_preset_tools(apify_service))
        except Exception:
            _apify_logger.warning(
                "Apify integration skipped — initialization failed", exc_info=True
            )

    return ToolCollection(*combined)
