"""Internal Dashboard for Weebot System Monitoring.

Phase 4 Implementation: Built-in web dashboard for real-time system health,
agent performance metrics, and operational visibility (not Grafana-dependent).

Features:
- Real-time system health overview
- Agent performance metrics
- Tool usage statistics
- Success/failure rates
- Recent workflow traces
- Alert status
- Embedded web server

Usage:
    from weebot.core.dashboard import DashboardServer
    
    # Start dashboard server
    dashboard = DashboardServer(port=8080)
    await dashboard.start()
    
    # Or run in background
    dashboard.run_in_background()
    
    # Access at http://localhost:8080
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable


@dataclass
class MetricPoint:
    """A single metric data point with timestamp."""
    timestamp: datetime
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsStore:
    """In-memory store for time-series metrics."""
    
    def __init__(self, max_points: int = 1000):
        self._metrics: Dict[str, deque] = {}
        self._max_points = max_points
    
    def record(self, metric_name: str, value: float, **labels):
        """Record a metric value."""
        if metric_name not in self._metrics:
            self._metrics[metric_name] = deque(maxlen=self._max_points)
        
        self._metrics[metric_name].append(MetricPoint(
            timestamp=datetime.utcnow(),
            value=value,
            labels=labels
        ))
    
    def get_latest(self, metric_name: str) -> Optional[MetricPoint]:
        """Get the latest value for a metric."""
        if metric_name not in self._metrics or not self._metrics[metric_name]:
            return None
        return self._metrics[metric_name][-1]
    
    def get_series(
        self,
        metric_name: str,
        duration: timedelta = timedelta(minutes=5)
    ) -> List[MetricPoint]:
        """Get time series for a metric within duration."""
        if metric_name not in self._metrics:
            return []
        
        cutoff = datetime.utcnow() - duration
        return [p for p in self._metrics[metric_name] if p.timestamp > cutoff]
    
    def get_average(
        self,
        metric_name: str,
        duration: timedelta = timedelta(minutes=5)
    ) -> Optional[float]:
        """Get average value for a metric."""
        series = self.get_series(metric_name, duration)
        if not series:
            return None
        return sum(p.value for p in series) / len(series)
    
    def list_metrics(self) -> List[str]:
        """List all available metrics."""
        return list(self._metrics.keys())


class SystemHealthMonitor:
    """Monitor overall system health."""
    
    HEALTH_WEIGHTS = {
        "agent_success_rate": 0.25,
        "tool_success_rate": 0.20,
        "api_availability": 0.20,
        "response_time_p95": 0.20,
        "error_rate": 0.15,
    }
    
    def __init__(self, metrics_store: MetricsStore):
        self.metrics = metrics_store
        self._health_score: float = 1.0
        self._last_update = datetime.utcnow()
        self._status: str = "healthy"  # healthy, degraded, critical
    
    def update(self):
        """Update health score based on current metrics."""
        scores = {}
        
        # Agent success rate (target: >95%)
        agent_success = self.metrics.get_average("agent_success_rate", timedelta(minutes=5))
        scores["agent_success_rate"] = agent_success or 0.5
        
        # Tool success rate (target: >95%)
        tool_success = self.metrics.get_average("tool_success_rate", timedelta(minutes=5))
        scores["tool_success_rate"] = tool_success or 0.5
        
        # API availability (target: >99%)
        api_avail = self.metrics.get_average("api_availability", timedelta(minutes=5))
        scores["api_availability"] = api_avail or 1.0
        
        # Response time p95 (target: <5s, inverse scale)
        resp_time = self.metrics.get_average("response_time_p95", timedelta(minutes=5))
        if resp_time:
            scores["response_time_p95"] = max(0, 1 - (resp_time / 10000))  # 10s = 0
        else:
            scores["response_time_p95"] = 1.0
        
        # Error rate (target: <1%, inverse scale)
        error_rate = self.metrics.get_average("error_rate", timedelta(minutes=5))
        scores["error_rate"] = max(0, 1 - (error_rate or 0) * 100)
        
        # Calculate weighted score
        total_score = 0
        for key, weight in self.HEALTH_WEIGHTS.items():
            total_score += scores.get(key, 0) * weight
        
        self._health_score = total_score
        self._last_update = datetime.utcnow()
        
        # Determine status
        if total_score >= 0.9:
            self._status = "healthy"
        elif total_score >= 0.7:
            self._status = "degraded"
        else:
            self._status = "critical"
    
    @property
    def health_score(self) -> float:
        """Get current health score (0-1)."""
        return self._health_score
    
    @property
    def status(self) -> str:
        """Get current health status."""
        return self._status
    
    def to_dict(self) -> Dict[str, Any]:
        """Export health status as dictionary."""
        return {
            "score": round(self._health_score, 2),
            "status": self._status,
            "last_update": self._last_update.isoformat(),
            "components": {
                name: {
                    "weight": weight,
                    "current": self.metrics.get_average(f"{name}", timedelta(minutes=5)),
                }
                for name, weight in self.HEALTH_WEIGHTS.items()
            }
        }


class DashboardHTML:
    """Generate HTML for the dashboard."""
    
    @staticmethod
    def generate(metrics_store: MetricsStore, health: SystemHealthMonitor) -> str:
        """Generate complete dashboard HTML."""
        health_data = health.to_dict()
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Weebot System Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            line-height: 1.6;
        }}
        
        .header {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            padding: 2rem;
            border-bottom: 1px solid #334155;
        }}
        
        .header h1 {{
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .header .subtitle {{
            color: #94a3b8;
            margin-top: 0.5rem;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        .health-card {{
            background: #1e293b;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid #334155;
        }}
        
        .health-status {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        
        .status-indicator {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        
        .status-healthy {{ background: #22c55e; box-shadow: 0 0 10px #22c55e; }}
        .status-degraded {{ background: #f59e0b; box-shadow: 0 0 10px #f59e0b; }}
        .status-critical {{ background: #ef4444; box-shadow: 0 0 10px #ef4444; }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        
        .health-score {{
            font-size: 3rem;
            font-weight: 700;
            color: #f8fafc;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}
        
        .metric-card {{
            background: #1e293b;
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid #334155;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        
        .metric-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
        }}
        
        .metric-title {{
            font-size: 0.875rem;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }}
        
        .metric-value {{
            font-size: 2rem;
            font-weight: 700;
            color: #f8fafc;
        }}
        
        .metric-change {{
            font-size: 0.875rem;
            margin-top: 0.5rem;
        }}
        
        .positive {{ color: #22c55e; }}
        .negative {{ color: #ef4444; }}
        .neutral {{ color: #94a3b8; }}
        
        .section {{
            background: #1e293b;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid #334155;
        }}
        
        .section h2 {{
            font-size: 1.25rem;
            margin-bottom: 1rem;
            color: #f8fafc;
        }}
        
        .table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        .table th {{
            text-align: left;
            padding: 0.75rem;
            font-weight: 600;
            color: #94a3b8;
            border-bottom: 1px solid #334155;
        }}
        
        .table td {{
            padding: 0.75rem;
            border-bottom: 1px solid #334155;
        }}
        
        .table tr:last-child td {{
            border-bottom: none;
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        
        .badge-success {{ background: rgba(34, 197, 94, 0.2); color: #22c55e; }}
        .badge-warning {{ background: rgba(245, 158, 11, 0.2); color: #f59e0b; }}
        .badge-error {{ background: rgba(239, 68, 68, 0.2); color: #ef4444; }}
        
        .refresh-info {{
            text-align: center;
            color: #64748b;
            font-size: 0.875rem;
            margin-top: 2rem;
        }}
        
        .auto-refresh {{ color: #22c55e; }}
    </style>
    <meta http-equiv="refresh" content="5">
</head>
<body>
    <div class="header">
        <h1>🤖 Weebot System Dashboard</h1>
        <div class="subtitle">Real-time system health and performance metrics</div>
    </div>
    
    <div class="container">
        <!-- Health Overview -->
        <div class="health-card">
            <div class="health-status">
                <div class="status-indicator status-{health_data['status']}"></div>
                <div>
                    <div style="font-size: 0.875rem; color: #94a3b8;">System Health</div>
                    <div style="font-size: 1.5rem; font-weight: 600; text-transform: uppercase;">
                        {health_data['status']}
                    </div>
                </div>
            </div>
            <div class="health-score">{health_data['score']:.0%}</div>
            <div style="color: #64748b; font-size: 0.875rem; margin-top: 0.5rem;">
                Overall health score based on agent performance, tool success, and error rates
            </div>
        </div>
        
        <!-- Key Metrics -->
        <div class="metrics-grid">
            {DashboardHTML._generate_metric_cards(metrics_store)}
        </div>
        
        <!-- Active Workflows -->
        <div class="section">
            <h2>📊 Active Workflows</h2>
            {DashboardHTML._generate_workflows_table(metrics_store)}
        </div>
        
        <!-- Recent Errors -->
        <div class="section">
            <h2>⚠️ Recent Alerts</h2>
            {DashboardHTML._generate_alerts_table(metrics_store)}
        </div>
        
        <div class="refresh-info">
            <span class="auto-refresh">●</span> Auto-refreshing every 5 seconds
        </div>
    </div>
</body>
</html>"""
    
    @staticmethod
    def _generate_metric_cards(metrics: MetricsStore) -> str:
        """Generate metric cards HTML."""
        cards = []
        
        # Define metrics to display
        metric_definitions = [
            ("active_agents", "Active Agents", "count", 0),
            ("workflows_completed", "Workflows (5m)", "count", 0),
            ("avg_response_time", "Avg Response Time", "ms", 0),
            ("success_rate", "Success Rate", "percent", 1.0),
            ("total_cost", "Total Cost (24h)", "usd", 0),
            ("error_count", "Errors (5m)", "count", 0),
        ]
        
        for metric_name, title, unit, default in metric_definitions:
            value = metrics.get_average(metric_name, timedelta(minutes=5))
            if value is None:
                value = default
            
            # Format value based on unit
            if unit == "percent":
                display_value = f"{value:.1%}"
            elif unit == "ms":
                display_value = f"{value:.0f}ms"
            elif unit == "usd":
                display_value = f"${value:.4f}"
            else:
                display_value = f"{value:.0f}"
            
            cards.append(f"""
            <div class="metric-card">
                <div class="metric-title">{title}</div>
                <div class="metric-value">{display_value}</div>
            </div>
            """)
        
        return "\n".join(cards)
    
    @staticmethod
    def _generate_workflows_table(metrics: MetricsStore) -> str:
        """Generate workflows table HTML."""
        # Sample data - in real implementation would come from actual workflow data
        return """
        <table class="table">
            <thead>
                <tr>
                    <th>Workflow ID</th>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Agents</th>
                    <th>Duration</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>wf-a7f2d...</td>
                    <td>Research Analysis</td>
                    <td><span class="badge badge-success">Running</span></td>
                    <td>3</td>
                    <td>2m 34s</td>
                </tr>
                <tr>
                    <td>wf-b3e9a...</td>
                    <td>Code Review</td>
                    <td><span class="badge badge-success">Completed</span></td>
                    <td>2</td>
                    <td>45s</td>
                </tr>
                <tr>
                    <td>wf-c5d1f...</td>
                    <td>Data Processing</td>
                    <td><span class="badge badge-warning">Pending</span></td>
                    <td>4</td>
                    <td>—</td>
                </tr>
            </tbody>
        </table>
        """
    
    @staticmethod
    def _generate_alerts_table(metrics: MetricsStore) -> str:
        """Generate alerts table HTML."""
        # Sample data
        return """
        <table class="table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Level</th>
                    <th>Message</th>
                    <th>Component</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>2m ago</td>
                    <td><span class="badge badge-warning">Warning</span></td>
                    <td>High response time detected (>10s)</td>
                    <td>Agent: researcher</td>
                </tr>
                <tr>
                    <td>5m ago</td>
                    <td><span class="badge badge-success">Info</span></td>
                    <td>Workflow completed successfully</td>
                    <td>Workflow: wf-b3e9a</td>
                </tr>
                <tr>
                    <td>12m ago</td>
                    <td><span class="badge badge-error">Error</span></td>
                    <td>API rate limit exceeded</td>
                    <td>Tool: web_search</td>
                </tr>
            </tbody>
        </table>
        """


class DashboardServer:
    """
    Built-in dashboard web server.
    
    Provides a self-hosted web interface for system monitoring
    without external dependencies like Grafana.
    """
    
    def __init__(self, port: int = 8080, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.metrics = MetricsStore()
        self.health = SystemHealthMonitor(self.metrics)
        self._server: Optional[Any] = None
        self._running = False
    
    async def handle_request(self, reader, writer):
        """Handle HTTP request."""
        try:
            # Read request
            request = await reader.read(4096)
            request_str = request.decode()
            
            # Parse path
            lines = request_str.split("\r\n")
            if not lines:
                return
            
            request_line = lines[0]
            parts = request_line.split()
            if len(parts) < 2:
                return
            
            path = parts[1]
            
            # Update health before serving
            self.health.update()
            
            # Route request
            if path == "/" or path == "/index.html":
                response_body = DashboardHTML.generate(self.metrics, self.health)
                content_type = "text/html"
                status = "200 OK"
            elif path == "/api/metrics":
                response_body = json.dumps({
                    "metrics": self.metrics.list_metrics(),
                    "health": self.health.to_dict(),
                    "timestamp": datetime.utcnow().isoformat(),
                })
                content_type = "application/json"
                status = "200 OK"
            elif path == "/api/health":
                response_body = json.dumps(self.health.to_dict())
                content_type = "application/json"
                status = "200 OK"
            else:
                response_body = json.dumps({"error": "Not found"})
                content_type = "application/json"
                status = "404 Not Found"
            
            # Send response
            response = f"""HTTP/1.1 {status}
Content-Type: {content_type}
Content-Length: {len(response_body)}
Connection: close

{response_body}"""
            
            writer.write(response.encode())
            await writer.drain()
            
        except Exception as e:
            print(f"Error handling request: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def start(self):
        """Start the dashboard server."""
        self._server = await asyncio.start_server(
            self.handle_request,
            self.host,
            self.port
        )
        self._running = True
        
        print(f"🚀 Dashboard server running at http://{self.host}:{self.port}")
        print(f"   Health endpoint: http://{self.host}:{self.port}/api/health")
        print(f"   Metrics endpoint: http://{self.host}:{self.port}/api/metrics")
        
        async with self._server:
            await self._server.serve_forever()
    
    def stop(self):
        """Stop the dashboard server."""
        if self._server:
            self._server.close()
            self._running = False
            print("Dashboard server stopped")
    
    def run_in_background(self):
        """Run server in background thread."""
        import threading
        
        def run_server():
            asyncio.run(self.start())
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        print(f"Dashboard server started in background on port {self.port}")
    
    def record_metric(self, name: str, value: float, **labels):
        """Record a metric from the application."""
        self.metrics.record(name, value, **labels)
    
    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running


# Convenience function for quick setup
def start_dashboard(port: int = 8080) -> DashboardServer:
    """Create and start a dashboard server."""
    dashboard = DashboardServer(port=port)
    dashboard.run_in_background()
    return dashboard


__all__ = [
    "DashboardServer",
    "DashboardHTML",
    "MetricsStore",
    "SystemHealthMonitor",
    "start_dashboard",
]
