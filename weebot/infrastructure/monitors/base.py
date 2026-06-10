"""Monitor ABC — lightweight periodic health check.

Each monitor runs in its own asyncio.Task inside HeartbeatManager.
``check()`` must be non-blocking (async def). The HeartbeatManager
cancels checks that exceed 2 × interval_seconds.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class MonitorState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass
class MonitorReport:
    """Result of a single monitor.check() call.

    Fields:
        state: Current monitor state classification.
        message: Human-readable description of current state.
        metadata: Optional structured data for logging or event payloads.
    """
    state: MonitorState
    message: str
    metadata: dict = field(default_factory=dict)


class Monitor(ABC):
    """One lightweight periodic check.

    Properties:
        name: Unique identifier (used in log lines and task names).
        interval_seconds: Seconds between consecutive ``check()`` calls.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def interval_seconds(self) -> int:
        ...

    @abstractmethod
    async def check(self) -> MonitorReport:
        """Run one health check. Must be non-blocking."""
        ...
