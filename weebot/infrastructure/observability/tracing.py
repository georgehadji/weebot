"""OpenTelemetry tracing — optional; no-op tracer when OTEL is not installed.

Usage
-----
    from weebot.infrastructure.observability.tracing import get_tracer

    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("operation") as span:
        span.set_attribute("key", "value")
        ...

To enable, set ``OTEL_EXPORTER_OTLP_ENDPOINT`` or run with ``opentelemetry-api``
and ``opentelemetry-sdk`` installed.  When neither is present, ``get_tracer``
returns the no-op ``opentelemetry-api`` default (``NoOpTracer``), which is a
zero-cost abstraction.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Attempt optional OTEL import ──────────────────────────────────────

try:
    from opentelemetry import trace as _trace
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor as _BatchSpanProcessor,
        ConsoleSpanExporter as _ConsoleExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as _OTLPSpanExporter,
    )
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    _trace = None  # type: ignore[assignment]


def init_tracing(
    service_name: str = "weebot",
    otlp_endpoint: Optional[str] = None,
    console_debug: bool = False,
) -> None:
    """Initialise the OpenTelemetry tracer provider.

    Called once at application startup (from ``Container.configure_defaults()``
    or the CLI entry point).  No-op when ``opentelemetry-sdk`` is not installed.
    """
    if not _OTEL_AVAILABLE:
        logger.info(
            "OpenTelemetry SDK not installed — tracing disabled. "
            "Install opentelemetry-api + opentelemetry-sdk to enable."
        )
        return

    provider = _TracerProvider()

    if otlp_endpoint:
        exporter = _OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(_BatchSpanProcessor(exporter))
        logger.info("OTLP trace exporter configured: %s", otlp_endpoint)

    if console_debug:
        provider.add_span_processor(_BatchSpanProcessor(_ConsoleExporter()))
        logger.info("Console trace exporter enabled (debug)")

    _trace.set_tracer_provider(provider)
    logger.info("Tracing initialised for service=%s", service_name)


def get_tracer(module_name: str = __name__) -> Any:
    """Return an OpenTelemetry tracer for *module_name*.

    Returns the no-op tracer when OTEL is not available, so callers can
    always ``with get_tracer(...).start_as_current_span(...)`` without
    guarding for the installation.
    """
    if _trace is not None:
        return _trace.get_tracer(module_name)
    # Return a minimal no-op that satisfies the context manager protocol
    return _NoOpTracer()


# ── No-op fallback when OTEL is absent ────────────────────────────────

class _NoOpSpan:
    """Minimal span that satisfies ``start_as_current_span`` without OTEL."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """Minimal tracer that returns ``_NoOpSpan`` context managers."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()
