"""Metrics collection for Weebot monitoring."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict


@dataclass
class MetricsSnapshot:
    """Snapshot of collected metrics.
    
    Attributes:
        session_count: Total sessions created
        session_duration_ms: List of session durations
        tool_executions: Count of tool executions by tool name
        tool_errors: Count of tool execution errors
        llm_calls: Count of LLM calls by model
        llm_tokens_in: Total input tokens
        llm_tokens_out: Total output tokens
        llm_latency_ms: List of LLM call latencies
        timestamp: When snapshot was taken
    """
    session_count: int = 0
    session_duration_ms: list[float] = field(default_factory=list)
    tool_executions: dict[str, int] = field(default_factory=dict)
    tool_errors: dict[str, int] = field(default_factory=dict)
    llm_calls: dict[str, int] = field(default_factory=dict)
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_latency_ms: list[float] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            "session_count": self.session_count,
            "session_duration_avg_ms": sum(self.session_duration_ms) / len(self.session_duration_ms) if self.session_duration_ms else 0,
            "session_duration_p99_ms": sorted(self.session_duration_ms)[int(len(self.session_duration_ms) * 0.99)] if self.session_duration_ms else 0,
            "tool_executions": self.tool_executions,
            "tool_errors": self.tool_errors,
            "llm_calls": self.llm_calls,
            "llm_tokens_in": self.llm_tokens_in,
            "llm_tokens_out": self.llm_tokens_out,
            "llm_latency_avg_ms": sum(self.llm_latency_ms) / len(self.llm_latency_ms) if self.llm_latency_ms else 0,
            "timestamp": self.timestamp,
        }


class MetricsCollector:
    """Collector for Weebot performance metrics.
    
    This class collects metrics during operation and provides
    snapshots for monitoring and debugging.
    
    Example:
        collector = MetricsCollector()
        
        # Record session
        collector.record_session_start()
        # ... session runs ...
        collector.record_session_complete(duration_ms=5000)
        
        # Get metrics
        snapshot = collector.get_snapshot()
        print(f"Sessions: {snapshot.session_count}")
    """
    
    def __init__(self) -> None:
        """Initialize the metrics collector."""
        self._session_count = 0
        self._session_durations: list[float] = []
        self._tool_executions: dict[str, int] = defaultdict(int)
        self._tool_errors: dict[str, int] = defaultdict(int)
        self._llm_calls: dict[str, int] = defaultdict(int)
        self._llm_tokens_in = 0
        self._llm_tokens_out = 0
        self._llm_latencies: list[float] = []
        self._max_history = 1000  # Keep last N measurements
    
    def record_session_start(self) -> None:
        """Record the start of a new session."""
        self._session_count += 1
    
    def record_session_complete(self, duration_ms: float) -> None:
        """Record completion of a session.
        
        Args:
            duration_ms: Session duration in milliseconds
        """
        self._session_durations.append(duration_ms)
        self._trim_history(self._session_durations)
    
    def record_tool_execution(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
    ) -> None:
        """Record a tool execution.
        
        Args:
            tool_name: Name of the tool
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
        """
        self._tool_executions[tool_name] += 1
        if not success:
            self._tool_errors[tool_name] += 1
    
    def record_llm_call(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
    ) -> None:
        """Record an LLM call.
        
        Args:
            model: Model name used
            tokens_in: Input token count
            tokens_out: Output token count
            latency_ms: Call latency in milliseconds
        """
        self._llm_calls[model] += 1
        self._llm_tokens_in += tokens_in
        self._llm_tokens_out += tokens_out
        self._llm_latencies.append(latency_ms)
        self._trim_history(self._llm_latencies)
    
    def get_snapshot(self) -> MetricsSnapshot:
        """Get a snapshot of current metrics.
        
        Returns:
            MetricsSnapshot with current values
        """
        return MetricsSnapshot(
            session_count=self._session_count,
            session_duration_ms=list(self._session_durations),
            tool_executions=dict(self._tool_executions),
            tool_errors=dict(self._tool_errors),
            llm_calls=dict(self._llm_calls),
            llm_tokens_in=self._llm_tokens_in,
            llm_tokens_out=self._llm_tokens_out,
            llm_latency_ms=list(self._llm_latencies),
        )
    
    def reset(self) -> None:
        """Reset all metrics to zero."""
        self._session_count = 0
        self._session_durations.clear()
        self._tool_executions.clear()
        self._tool_errors.clear()
        self._llm_calls.clear()
        self._llm_tokens_in = 0
        self._llm_tokens_out = 0
        self._llm_latencies.clear()
    
    def _trim_history(self, data: list) -> None:
        """Trim history list to max size."""
        if len(data) > self._max_history:
            # Keep most recent entries
            data[:] = data[-self._max_history:]


# Global metrics collector instance
_global_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance.
    
    Returns:
        MetricsCollector singleton
    """
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def reset_metrics_collector() -> None:
    """Reset the global metrics collector."""
    global _global_collector
    _global_collector = MetricsCollector()
