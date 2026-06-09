"""TracingAdapter — implements TracingPort via OTEL or no-op fallback."""
from __future__ import annotations

from typing import Any

from weebot.application.ports.tracing_port import Span, TracingPort


class _NoopSpan(Span):
    """Minimal no-op span."""

    def set_attribute(self, key: str, value: Any) -> None: pass
    def end(self) -> None: pass
    def __enter__(self) -> Span: return self
    def __exit__(self, *args: Any) -> None: pass


class TracingAdapter(TracingPort):
    """Wraps the OTEL tracer (or no-op fallback) behind the TracingPort."""

    def __init__(self) -> None:
        from weebot.infrastructure.observability.tracing import get_tracer
        self._tracer = get_tracer(__name__)

    def start_as_current_span(self, name: str) -> Span:
        raw = self._tracer.start_as_current_span(name)
        if isinstance(raw, Span):
            return raw
        return _OtelSpanWrapper(raw)

    def start_span(self, name: str) -> Span:
        raw = self._tracer.start_span(name)
        if isinstance(raw, Span):
            return raw
        return _OtelSpanWrapper(raw)


class _OtelSpanWrapper(Span):
    """Wraps a raw OTEL span/context-manager into the Span port interface."""

    def __init__(self, inner: Any):
        self._inner = inner
        self._active_span: Any = None  # set by __enter__

    def _target(self):
        """Return the best object for delegating span operations to."""
        if self._active_span is not None and hasattr(self._active_span, "set_attribute"):
            return self._active_span
        return self._inner

    def set_attribute(self, key: str, value: Any) -> None:
        t = self._target()
        if hasattr(t, "set_attribute"):
            t.set_attribute(key, value)

    def end(self) -> None:
        t = self._target()
        if hasattr(t, "end"):
            t.end()

    def __enter__(self) -> Span:
        self._active_span = self._inner.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        self._inner.__exit__(*args)
        self._active_span = None
