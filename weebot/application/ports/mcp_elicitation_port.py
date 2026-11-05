"""McpElicitationPort -- an MCP server asks the person a question mid-call (H12).

The server's ``elicitation/create`` request carries a message and a flat form schema. The
reply is one of the three MCP actions; ``content`` is set only with ``accept``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ElicitationReply:
    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any] | None = None


class McpElicitationPort(ABC):
    @abstractmethod
    async def elicit(
        self,
        server_name: str,
        message: str,
        schema: dict[str, Any],
        *,
        session_id: str = "",
    ) -> ElicitationReply:
        """Ask the person, or decline for them when no person can answer."""
