"""AuditPort — independent verification for agent outputs (Enhancement 11).

Provides a separate verification layer for multi-agent workflows.
Can be called by the SwarmTool after sub-agents complete, or by
an independent AuditTool.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.audit import AuditReport
from weebot.tools.base import ToolResult


class AuditPort(ABC):
    """Verifies agent outputs against configured audit dimensions."""

    @abstractmethod
    async def audit_output(
        self,
        output: str,
        skill_name: Optional[str] = None,
        session_id: str = "",
        agent_id: str = "",
    ) -> AuditReport:
        """Audit an agent's output and return a report.

        Args:
            output: The agent's output text to audit.
            skill_name: Skill used (for dimension selection).
            session_id: Optional session identifier.
            agent_id: Optional agent identifier.

        Returns:
            AuditReport with violations, verdict, and score.
        """
        ...

    @abstractmethod
    async def pass_threshold(self, report: AuditReport, skill_name: Optional[str] = None) -> bool:
        """Check if an audit report passes the threshold for its skill.

        Args:
            report: AuditReport to evaluate.
            skill_name: Skill name for threshold lookup.

        Returns:
            True if score meets or exceeds the skill's minimum.
        """
        ...
