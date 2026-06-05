"""MetricsPort — abstract interface for metric collection.

Allows Prometheus metrics to be switched to test doubles in unit tests.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class MetricsPort(ABC):
    """Collect and export application metrics."""

    @abstractmethod
    def inc_llm_call(self, provider: str, model: str, status: str) -> None:
        """Increment LLM call counter."""

    @abstractmethod
    def observe_llm_duration(self, provider: str, model: str, seconds: float) -> None:
        """Record LLM call duration in seconds."""

    @abstractmethod
    def inc_tool_call(self, tool: str, success: bool) -> None:
        """Increment tool execution counter."""

    @abstractmethod
    def inc_event(self, event_type: str) -> None:
        """Increment event counter."""

    @abstractmethod
    def set_active_sessions(self, count: int) -> None:
        """Set the gauge for active sessions."""

    @abstractmethod
    def render(self) -> str:
        """Return metrics text for the /metrics endpoint."""
