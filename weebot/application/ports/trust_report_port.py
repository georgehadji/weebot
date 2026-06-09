"""TrustReportPort — compute trust reports from code review + CoVe evidence.

Pure computation: implementations must not call LLMs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.trust_report import TrustReport


class TrustReportPort(ABC):
    """Compute a TrustReport from available evidence.

    Fail-open: return TrustReport(trust_band=CLEAN) on any error.
    """

    @abstractmethod
    async def compute(
        self,
        session_id: str,
        plan_steps: list[Any],   # list[Step]
        session_events: list[Any],  # list[AgentEvent]
    ) -> TrustReport:
        ...
