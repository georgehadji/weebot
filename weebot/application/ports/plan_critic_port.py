"""Plan Critic port — abstract interface for plan validation before execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.plan import Plan, PlanCritique


class PlanCriticPort(ABC):
    """Interface for plan validation.

    The critic reviews a plan before it reaches the executor, flagging
    wrong tool choices, missing constraints, unrealistic scope, or
    parallelism opportunities.
    """

    @abstractmethod
    async def critique(self, plan: Plan, context: dict[str, Any]) -> PlanCritique:
        """Critique a plan before execution.

        Args:
            plan: The plan to review.
            context: Execution context including task prompt, user preferences,
                     and available tools.

        Returns:
            PlanCritique with step scores, flaws, and a verdict.
        """
        ...
