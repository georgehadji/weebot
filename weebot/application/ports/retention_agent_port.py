"""RetentionAgentPort — abstract interface for session retention review."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.retention_review import RetentionReview


class RetentionAgentPort(ABC):
    """Review a completed session and recommend retention action.

    Fail-open: return PARK on any error.
    PRUNE verdict must never trigger any deletion — it is a recommendation only.
    """

    @abstractmethod
    async def review(
        self,
        session_id: str,
        session_summary: str,           # plan title + first 5 step descriptions
        trust_report: dict[str, Any] | None,  # serialised TrustReport or None
        error_count: int,
        tool_count: int,
    ) -> RetentionReview:
        ...
