"""OtelActivitySink — pushes ActivityEvents to an OpenTelemetry collector.

Implements :class:`~weebot.application.ports.analytics_port.AnalyticsSinkPort`.
Converts each :class:`~weebot.core.activity_stream.ActivityEvent` into an OTel
span and exports via OTLP gRPC.

Gracefully degrades to a no-op when ``opentelemetry`` packages are not installed
or ``WEEBOT_OTEL_ENDPOINT`` is unset.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from weebot.application.ports.analytics_port import AnalyticsSinkPort

if TYPE_CHECKING:
    from weebot.core.activity_stream import ActivityEvent

_log = logging.getLogger(__name__)

_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    _OTEL_AVAILABLE = True
except ImportError:
    pass


class OtelActivitySink(AnalyticsSinkPort):
    """Pushes ActivityEvents to an OTel collector via OTLP gRPC.

    Configured via environment variables:
    - ``WEEBOT_OTEL_ENDPOINT`` — OTLP gRPC endpoint (default: http://localhost:4317)
    - ``WEEBOT_OTEL_SERVICE_NAME`` — service name in spans (default: weebot)

    When OTel packages are missing or the endpoint is unset, the sink is a no-op.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        service_name: str | None = None,
    ) -> None:
        self._endpoint = endpoint or os.getenv(
            "WEEBOT_OTEL_ENDPOINT", ""
        )
        self._service_name = service_name or os.getenv(
            "WEEBOT_OTEL_SERVICE_NAME", "weebot"
        )

        self._tracer: trace.Tracer | None = None
        self._provider: TracerProvider | None = None

        if _OTEL_AVAILABLE and self._endpoint:
            self._setup_otel()
        elif not _OTEL_AVAILABLE:
            _log.debug("OpenTelemetry packages not installed — OtelActivitySink is a no-op")
        else:
            _log.debug("WEEBOT_OTEL_ENDPOINT not set — OtelActivitySink is a no-op")

    def _setup_otel(self) -> None:
        """Initialize the OTel tracer provider and exporter."""
        try:
            resource = Resource(attributes={SERVICE_NAME: self._service_name})
            self._provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=self._endpoint, insecure=True)
            self._provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(self._provider)
            self._tracer = trace.get_tracer(__name__)
            _log.info(
                "OtelActivitySink configured: endpoint=%s service=%s",
                self._endpoint,
                self._service_name,
            )
        except Exception:
            _log.exception("Failed to initialize OTel — sink is a no-op")
            self._tracer = None

    # ── AnalyticsSinkPort implementation ─────────────────────────────

    async def push(self, event: "ActivityEvent") -> None:
        """Convert an ActivityEvent to an OTel span and export it."""
        if self._tracer is None:
            return

        try:
            span = self._tracer.start_span(
                name=f"weebot.{event.kind}",
                attributes={
                    "project_id": event.project_id,
                    "kind": event.kind,
                    "message": event.message[:200],
                },
            )
            span.end()
        except Exception:
            _log.debug("OTel push failed — swallowing", exc_info=True)

    async def flush(self) -> None:
        """Force-flush the OTel span processor (idempotent)."""
        if self._provider is not None:
            try:
                self._provider.force_flush()
            except Exception:
                _log.debug("OTel force_flush failed — swallowing", exc_info=True)

    async def close(self) -> None:
        """Flush and shut down the OTel provider."""
        await self.flush()
        if self._provider is not None:
            try:
                self._provider.shutdown()
            except Exception:
                _log.debug("OTel shutdown failed — swallowing", exc_info=True)
