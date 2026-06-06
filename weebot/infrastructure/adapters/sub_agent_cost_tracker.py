"""SubAgentCostTracker — concrete in-memory cost budget tracker."""
from __future__ import annotations

from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.domain.models.sub_agent import AgentTier

# Estimated cost per token per tier (USD).  These are rough upper bounds
# used for budget gating, not for billing.
_COST_PER_TOKEN: dict[AgentTier, float] = {
    AgentTier.BUDGET: 0.0,       # FREE models
    AgentTier.STANDARD: 0.000003,  # ~$3/1M tokens
    AgentTier.PREMIUM: 0.000015,   # ~$15/1M tokens
}


class SubAgentCostTracker(SubAgentCostTrackerPort):
    """Simple in-memory cost tracker with a per-workflow USD budget."""

    def __init__(self, budget_usd: float = 0.50) -> None:
        self._budget = budget_usd
        self._spent: dict[str, dict] = {}
        self._total_tokens = 0
        self._total_cost = 0.0

    def can_afford(self, tier: AgentTier, estimated_tokens: int) -> bool:
        estimated_cost = estimated_tokens * _COST_PER_TOKEN[tier]
        return (self._total_cost + estimated_cost) <= self._budget

    def record_cost(self, agent_id: str, tokens: int, cost_usd: float) -> None:
        self._spent[agent_id] = {"tokens": tokens, "cost_usd": cost_usd}
        self._total_tokens += tokens
        self._total_cost += cost_usd  # use actual if provided, else estimate

    def remaining_budget(self) -> float:
        return max(0.0, self._budget - self._total_cost)

    def summary(self) -> dict:
        return {
            "budget_usd": self._budget,
            "total_spent_usd": self._total_cost,
            "remaining_usd": self.remaining_budget(),
            "total_tokens": self._total_tokens,
            "agents": len(self._spent),
        }
