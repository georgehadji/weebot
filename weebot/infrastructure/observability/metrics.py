"""Prometheus metrics for weebot observability.

Replaces the in-process MetricsCollector with structured,
exportable metric counters and histograms.
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY

# ── LLM calls ──
llm_calls_total = Counter(
    "weebot_llm_calls_total",
    "Total LLM API calls",
    ["model", "provider", "status"],
)
llm_call_duration_seconds = Histogram(
    "weebot_llm_duration_seconds",
    "LLM call duration",
    ["model", "provider"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# ── Tool calls ──
tool_calls_total = Counter(
    "weebot_tool_calls_total",
    "Total tool executions",
    ["tool", "success"],
)
tool_call_duration_seconds = Histogram(
    "weebot_tool_duration_seconds",
    "Tool execution duration",
    ["tool"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# ── Flow / state machine ──
flow_step_duration_seconds = Histogram(
    "weebot_flow_step_seconds",
    "Flow step execution time",
    ["flow_type", "state"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
session_active = Gauge(
    "weebot_sessions_active",
    "Currently active sessions",
)
session_total = Counter(
    "weebot_sessions_total",
    "Total sessions created",
)

# ── Event bus ──
events_published_total = Counter(
    "weebot_events_published_total",
    "Total events published",
    ["event_type"],
)
events_pending = Gauge(
    "weebot_events_pending",
    "Currently pending events in bus",
)

# ── Exceptions ──
exceptions_total = Counter(
    "weebot_exceptions_total",
    "Total exceptions raised",
    ["exception_type"],
)


def metrics_text() -> str:
    """Return the Prometheus exposition format text."""
    return generate_latest(REGISTRY).decode("utf-8")


def clear_metrics() -> None:
    """Reset all metrics (for testing)."""
    from prometheus_client import CollectorRegistry
    for collector in list(REGISTRY._collector_to_names):
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass
