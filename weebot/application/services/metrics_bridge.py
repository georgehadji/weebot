"""Metrics bridge — thin re-export of Prometheus metrics for application code.

Application-layer code MUST NOT import from weebot.infrastructure.observability.metrics
directly.  This bridge provides a lazy, failure-tolerant import so callers depend on
the application layer, not the infrastructure layer.

Usage:
    from weebot.application.services.metrics_bridge import get_metrics
    m = get_metrics()
    if m:
        m.flow_step_duration_seconds.labels(state=...).observe(...)
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_metrics_module = None


def get_metrics():
    """Return the Prometheus metrics module, or None if unavailable.

    The import is deferred and wrapped in try/except so a missing or
    broken metrics module never breaks application code.
    """
    global _metrics_module
    if _metrics_module is None:
        try:
            from weebot.infrastructure.observability import metrics as m
            _metrics_module = m
        except Exception:
            _metrics_module = False  # sentinel — metrics unavailable
            _log.debug("Prometheus metrics unavailable", exc_info=True)
    return _metrics_module if _metrics_module is not False else None


def reset_metrics_cache() -> None:
    """Reset the cached metrics module reference.

    Used by test fixtures for clean isolation.
    """
    global _metrics_module
    _metrics_module = None
