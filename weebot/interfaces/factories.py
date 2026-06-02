"""Factories for flows and tool collections."""
from __future__ import annotations

from typing import Optional

from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session
from weebot.infrastructure.mcp.mcp_toolkit_adapter import MCPToolkitAdapter
from weebot.tools.base import BaseTool, ToolCollection
from weebot.tools.tool_registry import RoleBasedToolRegistry


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
) -> BaseFlow:
    """Factory for creating agent flows."""
    if flow_type == "plan_act":
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
    extra_tools: Optional[list[BaseTool]] = None,
    llm_port: Optional[LLMPort] = None,
) -> ToolCollection:
    """Factory for building a ToolCollection for a given role and optional MCP config."""
    registry = RoleBasedToolRegistry()
    combined: list[BaseTool] = list(registry.create_tool_collection(role, llm_port=llm_port))

    if mcp_config:
        adapter = MCPToolkitAdapter()
        await adapter.initialize(mcp_config)
        combined.extend(adapter.get_tools())

    if extra_tools:
        combined.extend(extra_tools)

    return ToolCollection(*combined)
