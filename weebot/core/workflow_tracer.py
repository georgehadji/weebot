"""Workflow Tracing for Multi-Agent Execution Timeline.

Phase 4 Implementation: Execution timeline tracking, tool call tracing,
decision point logging, and error propagation tracking.

Features:
- Agent execution timeline visualization
- Tool call tracing with timing
- Decision point logging
- Error propagation tracking
- Span-based distributed tracing
- Export to multiple formats (JSON, HTML, Mermaid)

Usage:
    from weebot.core.workflow_tracer import WorkflowTracer, TraceSpan
    
    tracer = WorkflowTracer()
    
    # Start workflow trace
    with tracer.start_workflow("workflow-123", "Research Task") as workflow:
        # Trace agent execution
        with workflow.start_agent("researcher", "gpt-4") as agent:
            agent.add_decision("Selected 5 sources", confidence=0.95)
            
            with agent.start_tool_call("web_search") as tool:
                tool.set_input({"query": "AI ethics 2024"})
                result = search()
                tool.set_output({"results": 5})
        
        # Export trace
        trace_data = tracer.export_trace()
        tracer.to_html("trace.html")
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Generator, Union


def _utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class SpanStatus(Enum):
    """Status of a trace span."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class SpanType(Enum):
    """Type of trace span."""
    WORKFLOW = "workflow"
    AGENT = "agent"
    TOOL_CALL = "tool_call"
    DECISION = "decision"
    THOUGHT = "thought"
    ERROR = "error"


@dataclass
class TraceEvent:
    """An event within a trace span."""
    timestamp: datetime
    event_type: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.event_type,
            "message": self.message,
            "data": self.data,
        }


@dataclass
class TraceSpan:
    """
    A span in the workflow execution trace.
    
    Spans form a tree structure representing the execution hierarchy:
    Workflow -> Agents -> Tool Calls -> Decisions
    """
    span_id: str
    parent_id: Optional[str]
    span_type: SpanType
    name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: SpanStatus = SpanStatus.PENDING
    metadata: Dict[str, Any] = field(default_factory=dict)
    events: List[TraceEvent] = field(default_factory=list)
    children: List[TraceSpan] = field(default_factory=list)
    error_info: Optional[Dict[str, Any]] = None
    
    # Performance metrics
    duration_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    
    def __post_init__(self):
        if self.status == SpanStatus.PENDING:
            self.status = SpanStatus.RUNNING
    
    def add_event(self, event_type: str, message: str, **data):
        """Add an event to this span."""
        self.events.append(TraceEvent(
            timestamp=_utc_now(),
            event_type=event_type,
            message=message,
            data=data
        ))
    
    def add_decision(self, decision: str, confidence: Optional[float] = None, **context):
        """Record a decision point."""
        data = {"decision": decision, **context}
        if confidence is not None:
            data["confidence"] = confidence
        self.add_event("decision", f"Decision: {decision}", **data)
    
    def add_thought(self, thought: str, **context):
        """Record an agent's thought process."""
        self.add_event("thought", thought, **context)
    
    def set_error(self, error: Exception, **context):
        """Set error information for this span."""
        self.status = SpanStatus.ERROR
        self.error_info = {
            "type": type(error).__name__,
            "message": str(error),
            **context
        }
    
    def finish(self, status: Optional[SpanStatus] = None):
        """Mark this span as finished."""
        self.end_time = _utc_now()
        if status:
            self.status = status
        elif self.status == SpanStatus.RUNNING:
            self.status = SpanStatus.SUCCESS
        
        if self.start_time:
            self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "type": self.span_type.value,
            "name": self.name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "events": [e.to_dict() for e in self.events],
            "children": [c.to_dict() for c in self.children],
        }
        
        if self.error_info:
            result["error"] = self.error_info
        if self.input_tokens:
            result["input_tokens"] = self.input_tokens
        if self.output_tokens:
            result["output_tokens"] = self.output_tokens
        if self.cost_usd:
            result["cost_usd"] = self.cost_usd
        
        return result
    
    def get_critical_path(self) -> List[TraceSpan]:
        """Get the critical path (longest duration chain) through this span."""
        if not self.children:
            return [self]
        
        # Find child with longest duration
        longest_child = max(self.children, key=lambda c: c.duration_ms or 0)
        return [self] + longest_child.get_critical_path()
    
    def find_spans_by_type(self, span_type: SpanType) -> List[TraceSpan]:
        """Find all spans of a specific type."""
        results = []
        if self.span_type == span_type:
            results.append(self)
        for child in self.children:
            results.extend(child.find_spans_by_type(span_type))
        return results
    
    def find_errors(self) -> List[TraceSpan]:
        """Find all spans with errors."""
        results = []
        if self.status == SpanStatus.ERROR:
            results.append(self)
        for child in self.children:
            results.extend(child.find_errors())
        return results


class WorkflowTracer:
    """
    Tracer for workflow execution.
    
    Provides comprehensive tracing of multi-agent workflows including:
    - Execution timeline
    - Tool call performance
    - Decision points
    - Error propagation
    """
    
    def __init__(self, workflow_id: Optional[str] = None, workflow_name: str = "unnamed"):
        self.workflow_id = workflow_id or str(uuid.uuid4())
        self.workflow_name = workflow_name
        self.root_span: Optional[TraceSpan] = None
        self._current_span_stack: List[TraceSpan] = []
        self._all_spans: Dict[str, TraceSpan] = {}
        self.start_time = _utc_now()
        self.end_time: Optional[datetime] = None
    
    @contextmanager
    def start_workflow(self, workflow_id: Optional[str] = None, name: Optional[str] = None) -> Generator[WorkflowTracer, None, None]:
        """Start tracing a workflow."""
        if workflow_id:
            self.workflow_id = workflow_id
        if name:
            self.workflow_name = name
        
        self.root_span = TraceSpan(
            span_id=str(uuid.uuid4()),
            parent_id=None,
            span_type=SpanType.WORKFLOW,
            name=self.workflow_name,
            start_time=_utc_now(),
            metadata={"workflow_id": self.workflow_id}
        )
        self._current_span_stack.append(self.root_span)
        self._all_spans[self.root_span.span_id] = self.root_span
        
        try:
            yield self
        finally:
            if self.root_span:
                self.root_span.finish()
            self.end_time = _utc_now()
    
    @contextmanager
    def start_agent(self, agent_id: str, model: Optional[str] = None, **metadata) -> Generator[TraceSpan, None, None]:
        """Start tracing an agent execution."""
        parent = self._current_span_stack[-1] if self._current_span_stack else None
        
        span = TraceSpan(
            span_id=str(uuid.uuid4()),
            parent_id=parent.span_id if parent else None,
            span_type=SpanType.AGENT,
            name=agent_id,
            start_time=_utc_now(),
            metadata={"model": model, **metadata} if model else metadata
        )
        
        if parent:
            parent.children.append(span)
        
        self._current_span_stack.append(span)
        self._all_spans[span.span_id] = span
        
        try:
            yield span
        finally:
            span.finish()
            self._current_span_stack.pop()
    
    @contextmanager
    def start_tool_call(self, tool_name: str, **metadata) -> Generator[TraceSpan, None, None]:
        """Start tracing a tool call."""
        parent = self._current_span_stack[-1] if self._current_span_stack else None
        
        span = TraceSpan(
            span_id=str(uuid.uuid4()),
            parent_id=parent.span_id if parent else None,
            span_type=SpanType.TOOL_CALL,
            name=tool_name,
            start_time=_utc_now(),
            metadata=metadata
        )
        
        if parent:
            parent.children.append(span)
        
        self._current_span_stack.append(span)
        self._all_spans[span.span_id] = span
        
        try:
            yield span
        finally:
            span.finish()
            self._current_span_stack.pop()
    
    def record_decision(self, decision: str, confidence: Optional[float] = None, **context):
        """Record a decision in the current span."""
        if self._current_span_stack:
            self._current_span_stack[-1].add_decision(decision, confidence, **context)
    
    def record_thought(self, thought: str, **context):
        """Record a thought in the current span."""
        if self._current_span_stack:
            self._current_span_stack[-1].add_thought(thought, **context)
    
    def record_error(self, error: Exception, **context):
        """Record an error in the current span."""
        if self._current_span_stack:
            self._current_span_stack[-1].set_error(error, **context)
    
    def export_trace(self) -> Dict[str, Any]:
        """Export the complete trace as a dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "trace": self.root_span.to_dict() if self.root_span else None,
            "statistics": self.get_statistics(),
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the workflow execution."""
        if not self.root_span:
            return {}
        
        total_duration = (self.end_time - self.start_time).total_seconds() * 1000 if self.end_time else None
        
        agents = self.root_span.find_spans_by_type(SpanType.AGENT)
        tool_calls = self.root_span.find_spans_by_type(SpanType.TOOL_CALL)
        errors = self.root_span.find_errors()
        
        total_cost = sum(
            (a.cost_usd or 0) for a in agents
        )
        
        total_tokens = sum(
            (a.input_tokens or 0) + (a.output_tokens or 0) for a in agents
        )
        
        return {
            "total_duration_ms": total_duration,
            "agent_count": len(agents),
            "tool_call_count": len(tool_calls),
            "error_count": len(errors),
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "success_rate": (len(agents) - len(errors)) / len(agents) if agents else 1.0,
        }
    
    def get_critical_path(self) -> List[Dict[str, Any]]:
        """Get the critical path through the workflow."""
        if not self.root_span:
            return []
        
        path = self.root_span.get_critical_path()
        return [
            {
                "type": span.span_type.value,
                "name": span.name,
                "duration_ms": span.duration_ms,
            }
            for span in path
        ]
    
    def to_json(self, indent: int = 2) -> str:
        """Export trace to JSON string."""
        return json.dumps(self.export_trace(), indent=indent, default=str)
    
    def to_html(self, output_path: str):
        """Export trace to HTML visualization."""
        html = self._generate_html()
        with open(output_path, "w") as f:
            f.write(html)
    
    def _generate_html(self) -> str:
        """Generate HTML visualization of the trace."""
        stats = self.get_statistics()
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Workflow Trace: {self.workflow_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .stat-card {{ background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
        .stat-label {{ color: #7f8c8d; font-size: 14px; }}
        .timeline {{ background: white; padding: 20px; border-radius: 8px; }}
        .span {{ margin: 10px 0; padding: 15px; border-left: 4px solid #3498db; background: #f8f9fa; }}
        .span-agent {{ border-color: #9b59b6; }}
        .span-tool {{ border-color: #e67e22; }}
        .span-error {{ border-color: #e74c3c; background: #fdf2f2; }}
        .span-header {{ font-weight: bold; margin-bottom: 5px; }}
        .span-meta {{ font-size: 12px; color: #7f8c8d; }}
        .children {{ margin-left: 30px; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 Workflow Trace: {self.workflow_name}</h1>
        <p>ID: {self.workflow_id}</p>
    </div>
    
    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{stats.get('agent_count', 0)}</div>
            <div class="stat-label">Agents</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats.get('tool_call_count', 0)}</div>
            <div class="stat-label">Tool Calls</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats.get('error_count', 0)}</div>
            <div class="stat-label">Errors</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${stats.get('total_cost_usd', 0):.4f}</div>
            <div class="stat-label">Total Cost</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats.get('total_tokens', 0):,}</div>
            <div class="stat-label">Total Tokens</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats.get('success_rate', 1.0):.0%}</div>
            <div class="stat-label">Success Rate</div>
        </div>
    </div>
    
    <div class="timeline">
        <h2>Execution Timeline</h2>
        {self._render_span_html(self.root_span) if self.root_span else '<p>No trace data</p>'}
    </div>
</body>
</html>"""
        return html
    
    def _render_span_html(self, span: TraceSpan, depth: int = 0) -> str:
        """Render a span as HTML."""
        css_class = "span"
        if span.span_type == SpanType.AGENT:
            css_class += " span-agent"
        elif span.span_type == SpanType.TOOL_CALL:
            css_class += " span-tool"
        if span.status == SpanStatus.ERROR:
            css_class += " span-error"
        
        duration = f"{span.duration_ms:.1f}ms" if span.duration_ms else "N/A"
        
        html = f"""
        <div class="{css_class}" style="margin-left: {depth * 20}px">
            <div class="span-header">
                {span.span_type.value.upper()}: {span.name}
            </div>
            <div class="span-meta">
                Status: {span.status.value} | Duration: {duration}
            </div>
        """
        
        if span.error_info:
            html += f"""
            <div style="color: #e74c3c; margin-top: 10px;">
                <strong>Error:</strong> {span.error_info.get('type')}: {span.error_info.get('message')}
            </div>
            """
        
        if span.children:
            html += '<div class="children">'
            for child in span.children:
                html += self._render_span_html(child, depth + 1)
            html += '</div>'
        
        html += '</div>'
        return html
    
    def to_mermaid(self) -> str:
        """Generate Mermaid diagram of the workflow."""
        lines = ["graph TD"]
        
        def add_node(span: TraceSpan, parent_id: Optional[str] = None):
            node_id = f"node_{span.span_id[:8]}"
            label = f"{span.span_type.value}:{span.name}"
            
            # Style based on type
            if span.span_type == SpanType.WORKFLOW:
                lines.append(f"    {node_id}[{label}]:::workflow")
            elif span.span_type == SpanType.AGENT:
                lines.append(f"    {node_id}[{label}]:::agent")
            elif span.span_type == SpanType.TOOL_CALL:
                lines.append(f"    {node_id}({label}):::tool")
            
            if parent_id:
                lines.append(f"    {parent_id} --> {node_id}")
            
            for child in span.children:
                add_node(child, node_id)
        
        if self.root_span:
            add_node(self.root_span)
        
        lines.append("""
    classDef workflow fill:#2c3e50,stroke:#2c3e50,color:#fff
    classDef agent fill:#9b59b6,stroke:#9b59b6,color:#fff
    classDef tool fill:#e67e22,stroke:#e67e22,color:#fff
""")
        return "\n".join(lines)


# Convenience functions
def create_tracer(workflow_id: Optional[str] = None, name: str = "unnamed") -> WorkflowTracer:
    """Create a new workflow tracer."""
    return WorkflowTracer(workflow_id, name)


__all__ = [
    "WorkflowTracer",
    "TraceSpan",
    "TraceEvent",
    "SpanStatus",
    "SpanType",
    "create_tracer",
]
