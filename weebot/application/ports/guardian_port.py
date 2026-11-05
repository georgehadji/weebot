"""GuardianPort: a second opinion on one shell command before a person is asked (H18c).

The guardian sees the command and the step it serves, never a tool output, so it reads no
untrusted text. It may approve a command, refuse it, or escalate it to the person; escalate
is the answer to everything it cannot decide.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class GuardianVerdict(StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"


class GuardianPort(ABC):
    @abstractmethod
    async def review(self, command: str, step_description: str) -> GuardianVerdict:
        """Judge one command that no approval rule covers. Never raises."""
