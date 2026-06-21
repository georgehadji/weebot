"""LLMHealthMonitor — continuous LLM provider health probe.

Wraps ``HealthCheckService.check_all()`` and filters to LLM components.
No API quota is consumed — ``HealthCheckService`` does lightweight
connectivity checks (import verification), not generation calls.
"""
from __future__ import annotations

from weebot.infrastructure.observability.health_checks import (
    HealthCheckService,
    HealthStatus,
)
from .base import Monitor, MonitorReport, MonitorState


class LLMHealthMonitor(Monitor):
    """Probes LLM provider health every 2 minutes.

    Args:
        health_service: A pre-configured ``HealthCheckService`` instance.
    """

    name = "llm_health"
    interval_seconds = 120  # 2 minutes

    def __init__(self, health_service: HealthCheckService) -> None:
        self._health = health_service

    async def check(self) -> MonitorReport:
        """Run full health check and filter to LLM components."""
        report = await self._health.check_all()

        llm_components = [
            c for c in report.components
            if "llm" in c.name.lower()
            or "openrouter" in c.name.lower()
            or "xai" in c.name.lower()
        ]

        if not llm_components:
            return MonitorReport(
                MonitorState.HEALTHY,
                "No LLM components registered",
            )

        unhealthy = [c for c in llm_components if c.status == HealthStatus.UNHEALTHY]
        degraded = [c for c in llm_components if c.status == HealthStatus.DEGRADED]

        if unhealthy:
            return MonitorReport(
                MonitorState.CRITICAL,
                f"{len(unhealthy)} LLM provider(s) UNHEALTHY",
                metadata={"unhealthy": [c.name for c in unhealthy]},
            )
        if degraded:
            return MonitorReport(
                MonitorState.DEGRADED,
                f"{len(degraded)} LLM provider(s) degraded",
                metadata={"degraded": [c.name for c in degraded]},
            )
        return MonitorReport(
            MonitorState.HEALTHY,
            "All LLM providers healthy",
        )
