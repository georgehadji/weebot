"""DreamerPort — abstract interface for synthesizing signals into idea contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.idea_contract import IdeaContract


class DreamerPort(ABC):
    """Interface for the DreamerAgent — synthesizes ambient signals into ideas.

    Called periodically by the opportunity scan cycle.  Implementations must
    be fail-open: return [] on any error.
    """

    @abstractmethod
    async def dream(
        self,
        opportunity_proposals: list[Any],     # list[OpportunityProposal]
        failed_step_events: list[dict],       # from EventStorePort.query_recent_events
        audit_violations: list[Any],          # list[Violation] from recent AuditReports
        session_id: str = "",
    ) -> list[IdeaContract]:
        """Synthesize signals into IdeaContracts. Fail-open: return [] on any error."""
        ...
