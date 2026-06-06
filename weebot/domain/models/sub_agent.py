"""Sub-agent specification and result domain models.

Pydantic v2 frozen models. Zero external dependencies.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SubAgentRole(str, Enum):
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    CODER = "coder"
    DESIGNER = "designer"
    REVIEWER = "reviewer"
    AUTOMATION = "automation"
    PLANNER = "planner_sub"
    DOCUMENTER = "documentation"


class AgentTier(str, Enum):
    BUDGET = "budget"
    STANDARD = "standard"
    PREMIUM = "premium"


class DispatchStrategy(str, Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    FRESH_MIND = "fresh_mind"
    VOTED = "voted"


class SubAgentSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    role: SubAgentRole = Field(default=SubAgentRole.RESEARCHER)
    description: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    tier: AgentTier = Field(default=AgentTier.STANDARD)
    strategy: DispatchStrategy = Field(default=DispatchStrategy.PARALLEL)
    tools: list[str] = Field(default_factory=list)
    model: Optional[str] = Field(default=None)
    max_tool_calls: int = Field(default=15, ge=1, le=50)
    timeout_seconds: int = Field(default=300, ge=30, le=1800)
    output_schema: Optional[dict] = Field(default=None)

    def with_model(self, model: str) -> "SubAgentSpec":
        return self.model_copy(update={"model": model})

    def with_strategy(self, strategy: DispatchStrategy) -> "SubAgentSpec":
        return self.model_copy(update={"strategy": strategy})

    def with_tier(self, tier: AgentTier) -> "SubAgentSpec":
        return self.model_copy(update={"tier": tier})


class SubAgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class SubAgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    role: str = Field(default="")
    status: SubAgentStatus = Field(default=SubAgentStatus.PENDING)
    summary: str = Field(default="")
    data: dict = Field(default_factory=dict)
    error: Optional[str] = Field(default=None)
    model_used: str = Field(default="")
    tool_calls: int = Field(default=0)
    tokens_used: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    elapsed_seconds: float = Field(default=0.0)

    @property
    def is_success(self) -> bool:
        return self.status == SubAgentStatus.COMPLETED
