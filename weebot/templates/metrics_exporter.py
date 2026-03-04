"""Metrics Exporter for HARDEN Mode Monitoring.

This module provides helper functions to expose HARDEN mode metrics
in Prometheus format. Integrate with your existing metrics infrastructure.

Usage:
    from weebot.templates.metrics_exporter import HardenModeMetrics
    
    metrics = HardenModeMetrics()
    
    # In your request handler:
    metrics.export_privacy_metrics(audit_middleware)
    metrics.export_rate_limiter_metrics(rate_limiter)
    metrics.export_circuit_breaker_metrics(circuit_breaker)
    metrics.export_db_pool_metrics(pool_monitor)
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional


class HardenModeMetrics:
    """
    Helper class to export HARDEN mode metrics.
    
    This is a simplified implementation. For production use,
    integrate with your existing Prometheus client or metrics library.
    """
    
    def __init__(self, registry: Optional[Any] = None):
        """
        Initialize metrics exporter.
        
        Args:
            registry: Optional Prometheus registry to use
        """
        self.registry = registry
        self._metrics_cache: Dict[str, Any] = {}
    
    def export_privacy_metrics(self, audit_middleware) -> Dict[str, Any]:
        """
        Export privacy audit metrics.
        
        Args:
            audit_middleware: PrivacyAuditMiddleware instance
            
        Returns:
            Dict of metric name -> value
        """
        report = audit_middleware.get_report()
        
        metrics = {
            "weebot_privacy_compliance_score": report.compliance_score,
            "weebot_privacy_violations_total": report.violations,
            "weebot_privacy_blocked_total": report.blocked_operations,
            "weebot_privacy_queries_total": report.total_queries,
        }
        
        # Add violation breakdown
        for violation_type, count in report.violation_breakdown.items():
            metrics[f"weebot_privacy_violations_total{{type='{violation_type}'}}"] = count
        
        return metrics
    
    def export_rate_limiter_metrics(self, rate_limiter) -> Dict[str, Any]:
        """
        Export rate limiter metrics.
        
        Args:
            rate_limiter: RateLimiter instance
            
        Returns:
            Dict of metric name -> value
        """
        metrics_data = rate_limiter.get_metrics()
        
        return {
            "weebot_ratelimiter_active_buckets": metrics_data.get("active_buckets", 0),
            "weebot_ratelimiter_max_buckets": metrics_data.get("max_buckets", 10000),
            "weebot_ratelimiter_utilization": metrics_data.get("utilization", 0),
            "weebot_ratelimiter_evictions_total": metrics_data.get("eviction_count", 0),
            "weebot_ratelimiter_rejections_total": metrics_data.get("rejection_count", 0),
            "weebot_ratelimiter_total_requests": metrics_data.get("total_requests", 0),
        }
    
    def export_circuit_breaker_metrics(self, circuit_breaker) -> Dict[str, Any]:
        """
        Export circuit breaker metrics.
        
        Args:
            circuit_breaker: CircuitBreaker instance
            
        Returns:
            Dict of metric name -> value
        """
        metrics_data = circuit_breaker.get_metrics()
        
        return {
            "weebot_circuitbreaker_entities": metrics_data.get("tracked_entities", 0),
            "weebot_circuitbreaker_recovery_rate": metrics_data.get("recovery_rate", 0),
            "weebot_circuitbreaker_state_changes_total": metrics_data.get("state_changes_total", 0),
            "weebot_circuitbreaker_recovery_attempts_total": metrics_data.get("recovery_attempts", 0),
            "weebot_circuitbreaker_successful_recoveries_total": metrics_data.get("successful_recoveries", 0),
            "weebot_circuitbreaker_jitter_enabled": 1 if metrics_data.get("jitter_enabled") else 0,
        }
    
    def export_db_pool_metrics(self, pool_monitor) -> Dict[str, Any]:
        """
        Export database pool metrics.
        
        Args:
            pool_monitor: ConnectionPoolMonitor instance
            
        Returns:
            Dict of metric name -> value
        """
        metrics_data = pool_monitor.get_metrics()
        
        return {
            "weebot_dbpool_saturation": metrics_data.get("avg_saturation", 0),
            "weebot_dbpool_active_connections": metrics_data.get("active_connections", 0),
            "weebot_dbpool_total_acquisitions": metrics_data.get("total_acquisitions", 0),
            "weebot_dbpool_slow_acquisitions": metrics_data.get("slow_acquisitions", 0),
            "weebot_dbpool_timeouts": metrics_data.get("timeouts", 0),
            "weebot_dbpool_saturation_alerts_total": metrics_data.get("saturation_alerts", 0),
            "weebot_dbpool_pool_capacity": metrics_data.get("pool_capacity", 0),
        }
    
    def export_all_metrics(
        self,
        audit_middleware=None,
        rate_limiter=None,
        circuit_breaker=None,
        pool_monitor=None,
    ) -> Dict[str, Any]:
        """
        Export all HARDEN mode metrics.
        
        Args:
            audit_middleware: Optional PrivacyAuditMiddleware
            rate_limiter: Optional RateLimiter
            circuit_breaker: Optional CircuitBreaker
            pool_monitor: Optional ConnectionPoolMonitor
            
        Returns:
            Combined dict of all metrics
        """
        all_metrics = {}
        
        if audit_middleware:
            all_metrics.update(self.export_privacy_metrics(audit_middleware))
        
        if rate_limiter:
            all_metrics.update(self.export_rate_limiter_metrics(rate_limiter))
        
        if circuit_breaker:
            all_metrics.update(self.export_circuit_breaker_metrics(circuit_breaker))
        
        if pool_monitor:
            all_metrics.update(self.export_db_pool_metrics(pool_monitor))
        
        return all_metrics
    
    def to_prometheus_format(self, metrics: Dict[str, Any]) -> str:
        """
        Convert metrics dict to Prometheus exposition format.
        
        Args:
            metrics: Dict of metric name -> value
            
        Returns:
            Prometheus-formatted string
        """
        lines = []
        lines.append("# Weebot HARDEN Mode Metrics")
        lines.append(f"# Generated at {time.time()}")
        lines.append("")
        
        for name, value in sorted(metrics.items()):
            # Handle different types
            if isinstance(value, bool):
                value = 1 if value else 0
            elif isinstance(value, (int, float)):
                pass  # Keep as-is
            else:
                value = float(value) if value else 0
            
            lines.append(f"{name} {value}")
        
        return "\n".join(lines)


class MetricsMiddleware:
    """
    Middleware to automatically collect and expose metrics.
    
    Usage with Flask/FastAPI:
        app.add_middleware(MetricsMiddleware, 
                          audit=audit_middleware,
                          rate_limiter=rate_limiter)
    """
    
    def __init__(
        self,
        app=None,
        audit_middleware=None,
        rate_limiter=None,
        circuit_breaker=None,
        pool_monitor=None,
    ):
        self.app = app
        self.audit = audit_middleware
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
        self.pool_monitor = pool_monitor
        self.exporter = HardenModeMetrics()
    
    async def __call__(self, scope, receive, send):
        """ASGI middleware entry point."""
        if scope["path"] == "/metrics":
            # Return metrics
            metrics = self.exporter.export_all_metrics(
                self.audit,
                self.rate_limiter,
                self.circuit_breaker,
                self.pool_monitor,
            )
            body = self.exporter.to_prometheus_format(metrics)
            
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({
                "type": "http.response.body",
                "body": body.encode(),
            })
        else:
            # Pass through to app
            await self.app(scope, receive, send)


def create_metrics_endpoint(
    audit_middleware=None,
    rate_limiter=None,
    circuit_breaker=None,
    pool_monitor=None,
):
    """
    Create a simple metrics endpoint handler.
    
    Usage:
        from weebot.templates.metrics_exporter import create_metrics_endpoint
        
        @app.get("/metrics")
        async def metrics():
            return create_metrics_endpoint(
                audit_middleware=my_audit,
                rate_limiter=my_limiter,
            )
    """
    exporter = HardenModeMetrics()
    metrics = exporter.export_all_metrics(
        audit_middleware,
        rate_limiter,
        circuit_breaker,
        pool_monitor,
    )
    return exporter.to_prometheus_format(metrics)
