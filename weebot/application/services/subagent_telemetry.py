"""Subagent Telemetry — tracks cost, duration, and tool usage for subagents.

Collects runtime metrics from subagent invocations and publishes them
for observability and cost tracking.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SubagentInvocation:
    """Record of a single subagent RPC invocation."""
    id: str
    tool_calls: int = 0
    duration_seconds: float = 0.0
    estimated_tokens: int = 0
    estimated_cost_usd: float = 0.0
    success: bool = True
    error: str | None = None
    tools_used: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class SubagentTelemetry:
    """Collects and publishes subagent runtime metrics."""

    def __init__(self) -> None:
        self._invocations: list[SubagentInvocation] = []

    def record_invocation(self, invocation: SubagentInvocation) -> None:
        """Record a subagent invocation for tracking."""
        self._invocations.append(invocation)
        logger.info(
            "Subagent %s: %d tool calls, %.1fs, ~$%.4f",
            invocation.id, invocation.tool_calls,
            invocation.duration_seconds, invocation.estimated_cost_usd,
        )

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics."""
        if not self._invocations:
            return {
                "total_invocations": 0,
                "total_duration_seconds": 0,
                "total_tool_calls": 0,
                "total_cost_usd": 0.0,
                "success_rate": 1.0,
            }

        total_duration = sum(i.duration_seconds for i in self._invocations)
        total_calls = sum(i.tool_calls for i in self._invocations)
        total_cost = sum(i.estimated_cost_usd for i in self._invocations)
        successes = sum(1 for i in self._invocations if i.success)

        return {
            "total_invocations": len(self._invocations),
            "total_duration_seconds": round(total_duration, 2),
            "total_tool_calls": total_calls,
            "total_cost_usd": round(total_cost, 6),
            "success_rate": round(successes / len(self._invocations), 3) if self._invocations else 1.0,
        }

    def clear(self) -> None:
        """Clear all recorded invocations."""
        self._invocations.clear()
