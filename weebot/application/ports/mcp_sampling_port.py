"""McpSamplingPort -- what an MCP server's sampling request needs from the application (H12).

The client manager (infrastructure) turns an SDK request into a :class:`SamplingRequest`, asks
this port, and turns the :class:`SamplingResult` back. The session and taint of the tool call
that provoked it travel as a :class:`CallContext`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from weebot.domain.models.mcp import MCPSamplingPolicy


@dataclass(frozen=True)
class CallContext:
    session_id: str
    tainted: bool


class SamplingRequest:
    """Represents an MCP sampling/createMessage request.

    Mirrors the JSON-RPC params from the MCP specification.
    """

    def __init__(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        include_context: dict[str, Any] | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.messages = messages
        self.max_tokens = max_tokens
        self.stop_sequences = stop_sequences or []
        self.model = model
        self.system_prompt = system_prompt
        self.include_context = include_context or {}
        self.temperature = temperature
        self.metadata = metadata or {}


@dataclass
class SamplingResult:
    """Result of a sampling/createMessage operation."""

    content: list[dict[str, Any]]
    model: str
    stop_reason: str | None = None
    usage: dict[str, int] | None = None


class McpSamplingPort(ABC):
    @abstractmethod
    async def handle_sampling(
        self,
        server_name: str,
        request: SamplingRequest,
        policy: MCPSamplingPolicy,
        *,
        session_id: str | None = None,
        tainted: bool = False,
    ) -> SamplingResult | None:
        """Answer the request, or return None to decline it."""
