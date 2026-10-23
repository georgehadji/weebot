"""Agent capability profiles — static registry of what each role can do.

Which model a role runs on is routing, not a capability: it lives in
``weebot/config/model_refs.py`` (``ROLE_MODEL_CONFIG``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from weebot.domain.models.sub_agent import AgentTier, SubAgentRole


class AgentCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: SubAgentRole
    tier: AgentTier = Field(default=AgentTier.STANDARD)
    default_tools: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=4, ge=1, le=8)
    max_tool_calls: int = Field(default=15, ge=1, le=50)
    requires_fresh_context: bool = Field(default=False)


AGENT_CAPABILITIES: dict[SubAgentRole, AgentCapability] = {
    SubAgentRole.RESEARCHER: AgentCapability(
        role=SubAgentRole.RESEARCHER,
        tier=AgentTier.STANDARD,
        default_tools=["web_search", "browser_inspector", "knowledge", "file_editor"],
        max_concurrency=4,
        max_tool_calls=20,
    ),
    SubAgentRole.ANALYST: AgentCapability(
        role=SubAgentRole.ANALYST,
        tier=AgentTier.STANDARD,
        default_tools=["python_execute", "file_editor", "bash", "knowledge"],
        max_concurrency=2,
        max_tool_calls=15,
    ),
    SubAgentRole.CODER: AgentCapability(
        role=SubAgentRole.CODER,
        tier=AgentTier.STANDARD,
        default_tools=["bash", "python_execute", "file_editor", "web_search"],
        max_concurrency=2,
        max_tool_calls=30,
    ),
    SubAgentRole.DESIGNER: AgentCapability(
        role=SubAgentRole.DESIGNER,
        tier=AgentTier.PREMIUM,
        default_tools=["image_gen", "file_editor", "browser_inspector"],
        max_concurrency=3,
        max_tool_calls=20,
    ),
    SubAgentRole.REVIEWER: AgentCapability(
        role=SubAgentRole.REVIEWER,
        tier=AgentTier.BUDGET,
        default_tools=["file_editor", "web_search", "knowledge"],
        max_concurrency=2,
        max_tool_calls=10,
        requires_fresh_context=True,
    ),
    SubAgentRole.AUTOMATION: AgentCapability(
        role=SubAgentRole.AUTOMATION,
        tier=AgentTier.STANDARD,
        default_tools=["bash", "computer_use", "file_editor", "python_execute"],
        max_concurrency=2,
        max_tool_calls=25,
    ),
    SubAgentRole.PLANNER: AgentCapability(
        role=SubAgentRole.PLANNER,
        tier=AgentTier.BUDGET,
        default_tools=["file_editor", "knowledge", "web_search"],
        max_concurrency=1,
        max_tool_calls=8,
    ),
    SubAgentRole.DOCUMENTER: AgentCapability(
        role=SubAgentRole.DOCUMENTER,
        tier=AgentTier.BUDGET,
        default_tools=["file_editor", "knowledge", "web_search"],
        max_concurrency=2,
        max_tool_calls=12,
    ),
}
