"""ApprovalPort — how an ASK verdict on a tool call is resolved (ADR-013).

Implementations (``application/services/tool_approval.py``) are chosen per
channel: Deny (headless, default), Console (CLI with a TTY) and Flow pause
(web UI, chat gateways). DENY verdicts never reach this port.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApprovalOutcome(Enum):
    APPROVED = "approved"  # run this call now
    DENIED = "denied"  # refuse it
    PENDING = "pending"  # pause the flow and ask; a grant will be issued on "yes"


@dataclass(frozen=True)
class ToolCallApproval:
    """One call awaiting a human decision."""

    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    fingerprint: str  # core.approval.call_fingerprint(tool_name, arguments)
    guard: str  # the guard whose ASK verdict this is
    reason: str
    allow_always: str | None = None  # an egress host the human may allowlist for good
    extra: dict[str, Any] = field(default_factory=dict)


class ApprovalPort(ABC):
    @abstractmethod
    async def resolve(self, request: ToolCallApproval) -> ApprovalOutcome:
        """Decide this call: run it, refuse it, or pause the flow to ask."""
