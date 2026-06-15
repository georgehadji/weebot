"""Tests for Phase 4 Observability components.

Tests Structured Logging, Workflow Tracing, and Internal Dashboard.
"""
import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone


class TestStructuredLogger:
    """Test structured logging functionality."""
    
    def test_logger_creation(self):
        """Test logger can be created."""
        from weebot.core.structured_logger import StructuredLogger, get_logger
        
        logger = get_logger("test.logger")
        assert logger is not None
        assert logger.name == "test.logger"
    
    def test_log_record_creation(self):
        """Test log record can be created and serialized."""
        from weebot.core.structured_logger import StructuredLogRecord
        
        record = StructuredLogRecord(
            level="INFO",
            message="Test message",
            logger_name="test",
        )
        
        data = record.to_dict()
        assert data["level"] == "INFO"
        assert data["message"] == "Test message"
        assert "timestamp" in data
    
    def test_log_record_json_serialization(self):
        """Test log record serializes to valid JSON."""
        from weebot.core.structured_logger import StructuredLogRecord
        
        record = StructuredLogRecord(
            level="ERROR",
            message="Error occurred",
            logger_name="test",
            error_type="ValueError",
            error_category="VALIDATION",
        )
        
        json_str = record.to_json()
        data = json.loads(json_str)
        
        assert data["level"] == "ERROR"
        assert data["error_type"] == "ValueError"
        assert data["error_category"] == "VALIDATION"
    
    def test_correlation_id_context(self):
        """Test correlation ID context manager."""
        from weebot.core.structured_logger import StructuredLogger, get_correlation_id
        
        logger = StructuredLogger("test")
        
        # Initially no correlation ID
        assert get_correlation_id() is None
        
        # Set via context manager
        with logger.correlation_id("test-cid-123"):
            assert get_correlation_id() == "test-cid-123"
        
        # Reset after context
        assert get_correlation_id() is None
    
    def test_timer_context(self):
        """Test timer context manager."""
        from weebot.core.structured_logger import StructuredLogger
        
        logger = StructuredLogger("test")
        
        # Timer should complete without error
        with logger.timer("test_operation"):
            pass  # Immediate completion
    
    def test_error_categorization(self):
        """Test error categorization in logs."""
        from weebot.core.structured_logger import StructuredLogger, StructuredLogRecord
        
        logger = StructuredLogger("test")
        
        # Verify error categories exist
        assert "CRITICAL" in StructuredLogger.ERROR_CATEGORIES
        assert "ERROR" in StructuredLogger.ERROR_CATEGORIES
        assert "WARNING" in StructuredLogger.ERROR_CATEGORIES


class TestWorkflowTracer:
    """Test workflow tracing functionality."""
    
    def test_tracer_creation(self):
        """Test tracer can be created."""
        from weebot.core.workflow_tracer import WorkflowTracer
        
        tracer = WorkflowTracer("wf-test", "Test Workflow")
        assert tracer.workflow_id == "wf-test"
        assert tracer.workflow_name == "Test Workflow"
    
    def test_trace_span_creation(self):
        """Test trace span can be created."""
        from weebot.core.workflow_tracer import TraceSpan, SpanType, SpanStatus
        
        span = TraceSpan(
            span_id="span-123",
            parent_id=None,
            span_type=SpanType.WORKFLOW,
            name="Test Workflow",
            start_time=datetime.now(timezone.utc),
        )
        
        assert span.span_id == "span-123"
        assert span.span_type == SpanType.WORKFLOW
        assert span.status == SpanStatus.RUNNING
    
    def test_span_events(self):
        """Test events can be added to spans."""
        from weebot.core.workflow_tracer import TraceSpan, SpanType
        
        span = TraceSpan(
            span_id="span-123",
            parent_id=None,
            span_type=SpanType.AGENT,
            name="Test Agent",
            start_time=datetime.now(timezone.utc),
        )
        
        span.add_decision("Selected source A", confidence=0.95)
        span.add_thought("Processing input...")
        
        assert len(span.events) == 2
        assert span.events[0].event_type == "decision"
        assert span.events[1].event_type == "thought"
    
    def test_span_finish(self):
        """Test span can be finished."""
        from weebot.core.workflow_tracer import TraceSpan, SpanType, SpanStatus
        
        span = TraceSpan(
            span_id="span-123",
            parent_id=None,
            span_type=SpanType.TOOL_CALL,
            name="web_search",
            start_time=datetime.now(timezone.utc),
        )
        
        span.finish(SpanStatus.SUCCESS)
        
        assert span.status == SpanStatus.SUCCESS
        assert span.end_time is not None
        assert span.duration_ms is not None
    
    def test_span_dict_export(self):
        """Test span can be exported to dict."""
        from weebot.core.workflow_tracer import TraceSpan, SpanType
        
        span = TraceSpan(
            span_id="span-123",
            parent_id=None,
            span_type=SpanType.AGENT,
            name="Test Agent",
            start_time=datetime.now(timezone.utc),
        )
        span.finish()
        
        data = span.to_dict()
        
        assert data["span_id"] == "span-123"
        assert data["type"] == "agent"
        assert data["name"] == "Test Agent"
        assert "start_time" in data
        assert "duration_ms" in data
    
    def test_find_errors(self):
        """Test finding error spans."""
        from weebot.core.workflow_tracer import TraceSpan, SpanType, SpanStatus
        
        parent = TraceSpan(
            span_id="parent",
            parent_id=None,
            span_type=SpanType.WORKFLOW,
            name="workflow",
            start_time=datetime.now(timezone.utc),
        )
        
        child = TraceSpan(
            span_id="child",
            parent_id="parent",
            span_type=SpanType.AGENT,
            name="agent",
            start_time=datetime.now(timezone.utc),
        )
        child.status = SpanStatus.ERROR
        child.error_info = {"type": "ValueError", "message": "test"}
        parent.children.append(child)
        
        errors = parent.find_errors()
        assert len(errors) == 1
        assert errors[0].span_id == "child"
    
    def test_get_critical_path(self):
        """Test critical path calculation."""
        from weebot.core.workflow_tracer import TraceSpan, SpanType
        
        root = TraceSpan(
            span_id="root",
            parent_id=None,
            span_type=SpanType.WORKFLOW,
            name="workflow",
            start_time=datetime.now(timezone.utc),
        )
        root.duration_ms = 1000
        
        child = TraceSpan(
            span_id="child",
            parent_id="root",
            span_type=SpanType.AGENT,
            name="agent",
            start_time=datetime.now(timezone.utc),
        )
        child.duration_ms = 500
        root.children.append(child)
        
        path = root.get_critical_path()
        assert len(path) == 2
        assert path[0].span_id == "root"
        assert path[1].span_id == "child"
    
    def test_to_mermaid(self):
        """Test Mermaid diagram generation."""
        from weebot.core.workflow_tracer import WorkflowTracer
        
        tracer = WorkflowTracer("wf-123", "Test")
        
        # Export should produce valid Mermaid syntax
        mermaid = tracer.to_mermaid()
        assert "graph TD" in mermaid


class TestDashboard:
    """Test dashboard functionality."""
    
    def test_metrics_store_creation(self):
        """Test metrics store can be created."""
        from weebot.core.dashboard import MetricsStore
        
        store = MetricsStore()
        assert store is not None
    
    def test_metrics_store_record(self):
        """Test recording metrics."""
        from weebot.core.dashboard import MetricsStore
        
        store = MetricsStore()
        store.record("test_metric", 42.0, label="test")
        
        latest = store.get_latest("test_metric")
        assert latest is not None
        assert latest.value == 42.0
    
    def test_metrics_store_average(self):
        """Test calculating metric average."""
        from weebot.core.dashboard import MetricsStore
        
        store = MetricsStore()
        store.record("test_metric", 10.0)
        store.record("test_metric", 20.0)
        store.record("test_metric", 30.0)
        
        avg = store.get_average("test_metric")
        assert avg == 20.0
    
    def test_health_monitor_creation(self):
        """Test health monitor can be created."""
        from weebot.core.dashboard import MetricsStore, SystemHealthMonitor
        
        store = MetricsStore()
        monitor = SystemHealthMonitor(store)
        
        assert monitor is not None
        assert monitor.health_score == 1.0
        assert monitor.status == "healthy"
    
    def test_health_monitor_update(self):
        """Test health monitor updates."""
        from weebot.core.dashboard import MetricsStore, SystemHealthMonitor
        
        store = MetricsStore()
        monitor = SystemHealthMonitor(store)
        
        # Record some metrics
        store.record("agent_success_rate", 0.95)
        store.record("tool_success_rate", 0.98)
        store.record("api_availability", 1.0)
        
        monitor.update()
        
        # Health should be good with these metrics
        assert monitor.health_score > 0.8
        assert monitor.status in ["healthy", "degraded"]
    
    def test_dashboard_server_creation(self):
        """Test dashboard server can be created."""
        from weebot.core.dashboard import DashboardServer
        
        server = DashboardServer(port=9999)
        
        assert server.port == 9999
        assert server.metrics is not None
        assert server.health is not None
    
    def test_dashboard_html_generation(self):
        """Test dashboard HTML generation."""
        from weebot.core.dashboard import DashboardHTML, MetricsStore, SystemHealthMonitor
        
        store = MetricsStore()
        monitor = SystemHealthMonitor(store)
        
        html = DashboardHTML.generate(store, monitor)
        
        assert "<!DOCTYPE html>" in html
        assert "Weebot System Dashboard" in html
        assert "health-card" in html
        assert "metrics-grid" in html


class TestPhase4Integration:
    """Integration tests for Phase 4 components."""
    
    def test_end_to_end_logging_and_tracing(self):
        """Test logging and tracing work together."""
        from weebot.core.structured_logger import StructuredLogger
        from weebot.core.workflow_tracer import WorkflowTracer
        
        logger = StructuredLogger("test.integration")
        tracer = WorkflowTracer("wf-test", "Integration Test")
        
        # Start workflow trace
        with logger.correlation_id("test-correlation"):
            with logger.workflow_context("wf-test"):
                with tracer.start_workflow("wf-test", "Integration Test") as workflow:
                    # Log workflow start
                    logger.info("Workflow started", workflow_id="wf-test")
                    
                    # Trace agent execution
                    with tracer.start_agent("agent-1", "gpt-4") as agent_span:
                        logger.info("Agent started", agent_id="agent-1")
                        agent_span.add_decision("Test decision", confidence=0.9)
                    
                    logger.info("Workflow completed")
        
        # Verify trace data
        trace_data = tracer.export_trace()
        assert trace_data["workflow_id"] == "wf-test"
        assert "trace" in trace_data
        assert "statistics" in trace_data
    
    def test_metrics_recording(self):
        """Test recording various metrics."""
        from weebot.core.dashboard import DashboardServer
        
        dashboard = DashboardServer(port=9998)
        
        # Record various metrics
        dashboard.record_metric("agent_success_rate", 0.95)
        dashboard.record_metric("tool_success_rate", 0.98)
        dashboard.record_metric("response_time_p95", 2500.0)
        dashboard.record_metric("error_rate", 0.02)
        dashboard.record_metric("active_agents", 5.0)
        
        # Verify metrics stored
        assert "agent_success_rate" in dashboard.metrics.list_metrics()
        
        # Update health
        dashboard.health.update()
        assert dashboard.health.health_score > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
