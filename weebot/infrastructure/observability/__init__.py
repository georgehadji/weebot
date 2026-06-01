"""Observability infrastructure for Weebot.

Provides health checks, metrics collection, and monitoring capabilities
for production deployments.
"""

from .health_checks import (
    HealthCheckService,
    HealthReport,
    ComponentHealth,
    HealthStatus,
)
from weebot.infrastructure.observability.metrics import (
    llm_calls_total,
    tool_calls_total,
    flow_step_duration_seconds,
    session_active,
    session_total,
    events_published_total,
    exceptions_total,
)

__all__ = [
    "HealthCheckService",
    "HealthReport",
    "ComponentHealth",
    "HealthStatus",
    "llm_calls_total",
    "tool_calls_total",
    "flow_step_duration_seconds",
    "session_active",
    "session_total",
    "events_published_total",
    "exceptions_total",
]
