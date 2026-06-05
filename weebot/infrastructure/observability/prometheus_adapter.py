"""PrometheusMetricsAdapter — implements MetricsPort via prometheus_client.

Uses the existing metrics counters defined in ``weebot.infrastructure.observability.metrics``.
"""
from __future__ import annotations

from typing import Optional

from prometheus_client import generate_latest, REGISTRY

from weebot.application.ports.metrics_port import MetricsPort
from weebot.infrastructure.observability import metrics as _m


class PrometheusMetricsAdapter(MetricsPort):
    """Prometheus-backed implementation of MetricsPort."""

    def inc_llm_call(self, provider: str, model: str, status: str) -> None:
        _m.llm_calls_total.labels(model=model, provider=provider, status=status).inc()

    def observe_llm_duration(self, provider: str, model: str, seconds: float) -> None:
        _m.llm_call_duration_seconds.labels(model=model, provider=provider).observe(seconds)

    def inc_tool_call(self, tool: str, success: bool) -> None:
        _m.tool_calls_total.labels(tool=tool, success=str(success)).inc()

    def inc_event(self, event_type: str) -> None:
        try:
            _m.events_published_total.labels(event_type=event_type).inc()
        except Exception:
            pass

    def set_active_sessions(self, count: int) -> None:
        _m.session_active.set(count)

    def render(self) -> str:
        return generate_latest(REGISTRY).decode("utf-8")
