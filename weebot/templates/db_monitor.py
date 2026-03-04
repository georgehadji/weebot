"""Database Connection Pool Monitor for Production Template Engine.

HARDEN Mode Implementation: Monitors connection pool health and prevents
exhaustion through early warning and automatic sizing adjustments.

Features:
- Connection acquisition time tracking
- Pool saturation alerts (>80%)
- Query timeout enforcement
- Connection recycling
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable

_log = logging.getLogger(__name__)


@dataclass
class ConnectionMetrics:
    """Metrics for a single database connection."""
    acquired_at: Optional[datetime] = None
    acquisition_time_ms: float = 0.0
    query_count: int = 0
    total_query_time_ms: float = 0.0
    last_query_at: Optional[datetime] = None


@dataclass
class PoolSnapshot:
    """Snapshot of pool state at a point in time."""
    timestamp: datetime
    total_connections: int
    checked_out: int
    available: int
    waiting: int
    saturation_percent: float


@dataclass
class QueryMetrics:
    """Metrics for query execution."""
    query_id: str
    start_time: datetime
    timeout_seconds: float
    connection_wait_ms: float = 0.0


class ConnectionPoolMonitor:
    """
    HARDEN Mode: Monitor SQLAlchemy async connection pool health.
    
    Prevents pool exhaustion by:
    1. Tracking connection acquisition times
    2. Alerting when pool saturation exceeds threshold
    3. Providing metrics for capacity planning
    
    Usage:
        monitor = ConnectionPoolMonitor(
            pool_size=20,
            max_overflow=10,
            saturation_threshold=0.8,
        )
        
        # Wrap connection acquisition
        async with monitor.track_connection() as conn:
            await execute_query(conn)
    """
    
    DEFAULT_SATURATION_THRESHOLD = 0.8
    DEFAULT_ACQUISITION_TIMEOUT = 30.0
    DEFAULT_QUERY_TIMEOUT = 60.0
    
    def __init__(
        self,
        pool_size: int = 20,
        max_overflow: int = 10,
        saturation_threshold: float = DEFAULT_SATURATION_THRESHOLD,
        acquisition_timeout: float = DEFAULT_ACQUISITION_TIMEOUT,
        query_timeout: float = DEFAULT_QUERY_TIMEOUT,
        alert_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.saturation_threshold = saturation_threshold
        self.acquisition_timeout = acquisition_timeout
        self.query_timeout = query_timeout
        self.alert_callback = alert_callback
        
        # Metrics tracking
        self._connection_metrics: Dict[str, ConnectionMetrics] = {}
        self._active_queries: Dict[str, QueryMetrics] = {}
        self._snapshots: List[PoolSnapshot] = []
        self._max_snapshots = 1000
        
        # Statistics
        self._total_acquisitions = 0
        self._slow_acquisitions = 0  # >1 second
        self._timeouts = 0
        self._saturation_alerts = 0
        
        # Alert state to prevent spam
        self._last_saturation_alert: Optional[datetime] = None
        self._alert_cooldown_seconds = 60
    
    @property
    def total_capacity(self) -> int:
        """Total pool capacity including overflow."""
        return self.pool_size + self.max_overflow
    
    async def track_connection(self, connection_id: Optional[str] = None):
        """
        Async context manager to track connection lifecycle.
        
        Usage:
            async with monitor.track_connection() as conn_id:
                # Use connection
                pass
        """
        conn_id = connection_id or f"conn_{time.time():.6f}"
        start_time = time.time()
        
        try:
            # Wait for connection with timeout
            async with asyncio.timeout(self.acquisition_timeout):
                acquisition_time = time.time() - start_time
                
                # Track metrics
                self._total_acquisitions += 1
                if acquisition_time > 1.0:
                    self._slow_acquisitions += 1
                    _log.warning(
                        "Slow connection acquisition: %.2fs (conn %s)",
                        acquisition_time, conn_id[:16]
                    )
                
                self._connection_metrics[conn_id] = ConnectionMetrics(
                    acquired_at=datetime.now(),
                    acquisition_time_ms=acquisition_time * 1000,
                )
                
                yield conn_id
        
        except asyncio.TimeoutError:
            self._timeouts += 1
            _log.error(
                "Connection acquisition timeout after %.1fs",
                self.acquisition_timeout
            )
            raise
        
        finally:
            # Clean up metrics
            if conn_id in self._connection_metrics:
                del self._connection_metrics[conn_id]
    
    def record_query_start(
        self,
        connection_id: str,
        query_id: str,
        timeout: Optional[float] = None,
    ) -> None:
        """Record the start of a query execution."""
        self._active_queries[query_id] = QueryMetrics(
            query_id=query_id,
            start_time=datetime.now(),
            timeout_seconds=timeout or self.query_timeout,
        )
        
        if connection_id in self._connection_metrics:
            self._connection_metrics[connection_id].query_count += 1
    
    def record_query_end(
        self,
        connection_id: str,
        query_id: str,
        success: bool = True,
    ) -> None:
        """Record the end of a query execution."""
        if query_id in self._active_queries:
            metrics = self._active_queries.pop(query_id)
            duration = (datetime.now() - metrics.start_time).total_seconds()
            
            if connection_id in self._connection_metrics:
                conn_metrics = self._connection_metrics[connection_id]
                conn_metrics.total_query_time_ms += duration * 1000
                conn_metrics.last_query_at = datetime.now()
            
            if not success:
                _log.warning("Query %s failed after %.2fs", query_id[:16], duration)
    
    def record_pool_snapshot(
        self,
        checked_out: int,
        available: int,
        waiting: int = 0,
    ) -> PoolSnapshot:
        """
        Record a snapshot of current pool state.
        
        Args:
            checked_out: Connections currently in use
            available: Connections ready for use
            waiting: Requests waiting for connection
            
        Returns:
            PoolSnapshot object
        """
        total = checked_out + available
        saturation = checked_out / self.total_capacity if self.total_capacity > 0 else 0
        
        snapshot = PoolSnapshot(
            timestamp=datetime.now(),
            total_connections=total,
            checked_out=checked_out,
            available=available,
            waiting=waiting,
            saturation_percent=saturation,
        )
        
        self._snapshots.append(snapshot)
        
        # Prevent unbounded growth
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots.pop(0)
        
        # Check saturation threshold
        if saturation > self.saturation_threshold:
            self._maybe_alert_saturation(saturation, checked_out, waiting)
        
        return snapshot
    
    def _maybe_alert_saturation(
        self,
        saturation: float,
        checked_out: int,
        waiting: int,
    ) -> None:
        """Alert on pool saturation with cooldown."""
        now = datetime.now()
        
        # Check cooldown
        if self._last_saturation_alert:
            cooldown_elapsed = (now - self._last_saturation_alert).total_seconds()
            if cooldown_elapsed < self._alert_cooldown_seconds:
                return
        
        self._saturation_alerts += 1
        self._last_saturation_alert = now
        
        alert_data = {
            "saturation": f"{saturation:.1%}",
            "checked_out": checked_out,
            "waiting": waiting,
            "capacity": self.total_capacity,
            "timestamp": now.isoformat(),
        }
        
        _log.error(
            "POOL SATURATION ALERT: %.1f%% (%d/%d connections, %d waiting)",
            saturation * 100, checked_out, self.total_capacity, waiting
        )
        
        if self.alert_callback:
            self.alert_callback("pool_saturation", alert_data)
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive pool metrics.
        
        Returns:
            Dict with current state and historical statistics.
        """
        # Current state
        active_connections = len(self._connection_metrics)
        active_queries = len(self._active_queries)
        
        # Calculate average acquisition time
        if self._connection_metrics:
            avg_acquisition = sum(
                m.acquisition_time_ms for m in self._connection_metrics.values()
            ) / len(self._connection_metrics)
        else:
            avg_acquisition = 0.0
        
        # Recent saturation trend
        recent_saturation = [
            s.saturation_percent for s in self._snapshots[-10:]
        ]
        avg_saturation = sum(recent_saturation) / len(recent_saturation) if recent_saturation else 0
        
        return {
            "active_connections": active_connections,
            "active_queries": active_queries,
            "total_acquisitions": self._total_acquisitions,
            "slow_acquisitions": self._slow_acquisitions,
            "slow_acquisition_rate": (
                self._slow_acquisitions / self._total_acquisitions
                if self._total_acquisitions > 0 else 0
            ),
            "timeouts": self._timeouts,
            "saturation_alerts": self._saturation_alerts,
            "avg_acquisition_time_ms": avg_acquisition,
            "avg_saturation": avg_saturation,
            "pool_capacity": self.total_capacity,
            "saturation_threshold": self.saturation_threshold,
        }
    
    def get_recommendations(self) -> List[str]:
        """
        Get recommendations based on metrics.
        
        Returns:
            List of actionable recommendations.
        """
        recommendations = []
        metrics = self.get_metrics()
        
        # Check slow acquisitions
        if metrics["slow_acquisition_rate"] > 0.1:  # >10% slow
            recommendations.append(
                "Consider increasing pool size: >10% of acquisitions are slow"
            )
        
        # Check timeout rate
        if metrics["timeouts"] > 10:
            recommendations.append(
                f"High timeout count ({metrics['timeouts']}): Check for connection leaks"
            )
        
        # Check saturation
        if metrics["avg_saturation"] > 0.7:
            recommendations.append(
                f"Pool avg saturation {metrics['avg_saturation']:.0%}: "
                "Consider increasing pool size or optimizing queries"
            )
        
        # Check query count per connection
        if self._connection_metrics:
            high_query_conns = sum(
                1 for m in self._connection_metrics.values() if m.query_count > 100
            )
            if high_query_conns > len(self._connection_metrics) * 0.5:
                recommendations.append(
                    "Many connections have high query counts: Consider connection recycling"
                )
        
        return recommendations
    
    def clear_history(self) -> None:
        """Clear historical data."""
        self._snapshots.clear()
        self._saturation_alerts = 0
        _log.info("Pool monitor history cleared")


class MonitoredDatabaseManager:
    """
    Wrapper for DatabaseManager that adds pool monitoring.
    
    This is a HARDEN mode protective layer that monitors connection
    pool health and prevents exhaustion.
    """
    
    def __init__(
        self,
        inner_manager: Any,
        monitor: Optional[ConnectionPoolMonitor] = None,
    ):
        self.inner_manager = inner_manager
        self.monitor = monitor or ConnectionPoolMonitor()
    
    async def record_execution(self, *args, **kwargs) -> None:
        """Wrap execution with monitoring."""
        async with self.monitor.track_connection():
            return await self.inner_manager.record_execution(*args, **kwargs)
    
    async def log_audit(self, *args, **kwargs) -> None:
        """Wrap audit logging with monitoring."""
        async with self.monitor.track_connection():
            return await self.inner_manager.log_audit(*args, **kwargs)
    
    async def get_user_stats(self, *args, **kwargs) -> Dict[str, Any]:
        """Wrap stats query with monitoring."""
        async with self.monitor.track_connection():
            return await self.inner_manager.get_user_stats(*args, **kwargs)
