"""TracingPort — abstract interface for distributed tracing.

Allows OpenTelemetry to be switched to test doubles in unit tests
and prevents application-layer imports of infrastructure tracing modules.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Span(ABC):
    """Abstract span — mirrors a subset of opentelemetry.trace.Span."""

    @abstractmethod
    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""

    @abstractmethod
    def end(self) -> None:
        """End the span."""

    @abstractmethod
    def __enter__(self) -> "Span":
        """Enter span context."""

    @abstractmethod
    def __exit__(self, *args: Any) -> None:
        """Exit span context."""


class TracingPort(ABC):
    """Port for distributed tracing operations."""

    @abstractmethod
    def start_as_current_span(self, name: str) -> Span:
        """Start a span as the current context. Returns a context-manager Span."""

    @abstractmethod
    def start_span(self, name: str) -> Span:
        """Start a span without making it current. Caller must call .end()."""
