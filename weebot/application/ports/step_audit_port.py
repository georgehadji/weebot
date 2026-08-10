"""StepAuditPort — environment-grounded evidence check for a single step.

Distinct from AuditPort: AuditPort audits an agent's *output text* against
configured dimensions (regex/pattern matching). StepAuditPort audits a step's
*ToolEvents* against the real environment (filesystem, command output) — it
answers "did the environment change the way the step claims", not "does the
text look safe".
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from weebot.domain.models.audit import AuditReport
from weebot.domain.models.event import ToolEvent
from weebot.domain.models.plan import Step


class StepAuditPort(ABC):
    """Environment-grounded evidence check, scoped to one step's tool events."""

    @abstractmethod
    async def audit_step(
        self,
        step: Step | None,
        events: Sequence[ToolEvent],
        session_id: str = "",
    ) -> AuditReport:
        """Check *events* for evidence that *step* actually happened.

        Reads ToolEvent results and inspects the real environment (files,
        command output) directly — never the LLM's own summary of what it
        did. Returns an AuditReport whose ``verdict`` reflects whether the
        evidence supports completion.

        *step* may be ``None`` for session-wide (non-per-step) callers —
        current gates do not key off step identity, only off *events*.
        """
        ...
