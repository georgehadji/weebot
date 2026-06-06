"""Port for tracking sub-agent cost budgets within a workflow."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.sub_agent import AgentTier


class SubAgentCostTrackerPort(ABC):
    """Abstract interface for per-workflow cost tracking and gating."""

    @abstractmethod
    def can_afford(self, tier: AgentTier, estimated_tokens: int) -> bool:
        """Return True if the remaining budget can cover *estimated_tokens* at *tier*."""

    @abstractmethod
    def record_cost(self, agent_id: str, tokens: int, cost_usd: float) -> None:
        """Record actual cost incurred by a sub-agent."""

    @abstractmethod
    def remaining_budget(self) -> float:
        """Return the remaining budget in USD."""

    @abstractmethod
    def summary(self) -> dict:
        """Return a dict with cost tracking summary for reporting."""
