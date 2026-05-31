"""Memory monitoring and management for weebot."""
from __future__ import annotations

import asyncio
import gc
import logging
import tracemalloc
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import psutil, provide fallback if not available
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


@dataclass
class MemoryThresholds:
    """Memory threshold configuration."""
    warning_percent: float = 75.0   # % of max before warning
    critical_percent: float = 85.0  # % of max before critical action
    max_mb: int = 2048              # Hard limit in MB


@dataclass 
class MemoryStats:
    """Current memory statistics."""
    rss_mb: float
    python_current_mb: float
    python_peak_mb: float
    max_mb: int
    percent: float
    system_percent: Optional[float] = None  # System-wide memory %
    timestamp: float = 0.0


class MemoryMonitor:
    """
    Monitor system memory and trigger actions at thresholds.
    
    Monitors both process RSS and Python heap allocation. Triggers:
    - Warning: Log alert, trigger GC
    - Critical: Force GC, notify callbacks, reduce parallelism
    - Max exceeded: Emergency cleanup, reject new work
    
    Usage:
        monitor = MemoryMonitor(check_interval=10.0)
        monitor.register_callback(lambda level, stats: print(f"{level}: {stats}"))
        
        # Start monitoring
        await monitor.start()
        
        # Check if can accept work
        if monitor.should_accept_work():
            await process_request()
        
        # Stop monitoring
        monitor.stop()
    
    Attributes:
        thresholds: Memory threshold configuration
        check_interval: Seconds between checks
    """
    
    def __init__(
        self,
        thresholds: Optional[MemoryThresholds] = None,
        check_interval: float = 10.0,
        enable_gc_collection: bool = True
    ):
        """
        Initialize memory monitor.
        
        Args:
            thresholds: Memory thresholds (uses defaults if None)
            check_interval: Seconds between memory checks
            enable_gc_collection: Whether to trigger GC on high memory
        """
        self.thresholds = thresholds or MemoryThresholds()
        self.check_interval = check_interval
        self.enable_gc_collection = enable_gc_collection
        
        self._callbacks: List[Callable[[str, MemoryStats], None]] = []
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Initialize process info if available
        self._process = None
        if PSUTIL_AVAILABLE:
            self._process = psutil.Process()
        
        # Initialize tracemalloc for Python heap tracking
        tracemalloc.start()
        
        # Statistics
        self._stats = {
            "warning_count": 0,
            "critical_count": 0,
            "gc_collections": 0,
            "peak_rss_mb": 0.0
        }
        
        self._last_stats: Optional[MemoryStats] = None
    
    def register_callback(self, callback: Callable[[str, MemoryStats], None]) -> None:
        """
        Register a callback for memory events.
        
        Args:
            callback: Function(level: str, stats: MemoryStats) -> None
                level is "warning", "critical", or "normal"
        """
        self._callbacks.append(callback)
        logger.debug(f"Registered memory callback (total: {len(self._callbacks)})")
    
    async def start(self) -> None:
        """Start background memory monitoring."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(
            f"Memory monitor started (interval={self.check_interval}s, "
            f"warning={self.thresholds.warning_percent}%, "
            f"critical={self.thresholds.critical_percent}%)"
        )
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                stats = self.check_memory()
                self._last_stats = stats
                
                # Update peak
                if stats.rss_mb > self._stats["peak_rss_mb"]:
                    self._stats["peak_rss_mb"] = stats.rss_mb
                
                # Check thresholds and trigger actions
                if stats.percent >= self.thresholds.critical_percent:
                    await self._handle_critical(stats)
                elif stats.percent >= self.thresholds.warning_percent:
                    await self._handle_warning(stats)
                else:
                    # Memory is normal
                    pass
                
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory monitor error: {e}")
                await asyncio.sleep(self.check_interval)
    
    def check_memory(self) -> MemoryStats:
        """
        Get current memory statistics.
        
        Returns:
            MemoryStats with current memory usage
        """
        import time
        
        # Get RSS (Resident Set Size)
        rss_mb = 0.0
        system_percent = None
        
        if self._process:
            try:
                rss_mb = self._process.memory_info().rss / (1024 * 1024)
                system_percent = psutil.virtual_memory().percent
            except Exception as e:
                logger.debug(f"Could not get process memory: {e}")
        
        # Get Python heap allocation
        current, peak = tracemalloc.get_traced_memory()
        python_current_mb = current / (1024 * 1024)
        python_peak_mb = peak / (1024 * 1024)
        
        # Calculate percentage of max
        percent = (rss_mb / self.thresholds.max_mb) * 100
        
        return MemoryStats(
            rss_mb=rss_mb,
            python_current_mb=python_current_mb,
            python_peak_mb=python_peak_mb,
            max_mb=self.thresholds.max_mb,
            percent=percent,
            system_percent=system_percent,
            timestamp=time.time()
        )
    
    async def _handle_warning(self, stats: MemoryStats) -> None:
        """Handle warning threshold breach."""
        self._stats["warning_count"] += 1
        
        logger.warning(
            f"Memory warning: {stats.rss_mb:.0f}MB "
            f"({stats.percent:.1f}% of {self.thresholds.max_mb}MB max)"
        )
        
        # Trigger GC if enabled
        if self.enable_gc_collection:
            collected = gc.collect()
            self._stats["gc_collections"] += 1
            logger.debug(f"GC collected {collected} objects")
        
        # Notify callbacks
        await self._notify_callbacks("warning", stats)
    
    async def _handle_critical(self, stats: MemoryStats) -> None:
        """Handle critical threshold breach."""
        self._stats["critical_count"] += 1
        
        logger.error(
            f"Memory CRITICAL: {stats.rss_mb:.0f}MB "
            f"({stats.percent:.1f}% of {self.thresholds.max_mb}MB max)"
        )
        
        # Force aggressive GC
        if self.enable_gc_collection:
            gc.collect()
            gc.collect()  # Second pass for cycles
            self._stats["gc_collections"] += 2
        
        # Notify callbacks (they should take action like reducing parallelism)
        await self._notify_callbacks("critical", stats)
    
    async def _notify_callbacks(self, level: str, stats: MemoryStats) -> None:
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(level, stats)
                else:
                    callback(level, stats)
            except Exception as e:
                logger.warning(f"Memory callback error: {e}")
    
    def should_accept_work(self) -> bool:
        """
        Check if system can accept new work.
        
        Returns:
            False if memory is at critical levels
        """
        stats = self.check_memory()
        
        # Reject new work if near max
        if stats.percent >= 95.0:
            logger.warning(f"Rejecting work: memory at {stats.percent:.1f}%")
            return False
        
        return True
    
    def get_recommended_workers(self, current_workers: int) -> int:
        """
        Get recommended worker count based on memory pressure.
        
        Args:
            current_workers: Current number of workers
        
        Returns:
            Recommended worker count (may be lower than current)
        """
        stats = self.check_memory()
        
        if stats.percent >= self.thresholds.critical_percent:
            # Reduce significantly
            return max(1, current_workers // 2)
        elif stats.percent >= self.thresholds.warning_percent:
            # Reduce slightly
            return max(1, current_workers - 1)
        
        return current_workers
    
    def stop(self) -> None:
        """Stop memory monitoring."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            logger.info("Memory monitor stopped")
    
    def get_stats(self) -> Dict:
        """Get monitor statistics."""
        return {
            "thresholds": {
                "warning_percent": self.thresholds.warning_percent,
                "critical_percent": self.thresholds.critical_percent,
                "max_mb": self.thresholds.max_mb,
            },
            "current": self._last_stats.__dict__ if self._last_stats else None,
            "events": self._stats.copy(),
            "running": self._running,
            "callbacks_registered": len(self._callbacks),
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.stop()


class MemoryAwareMixin:
    """
    Mixin for making classes memory-aware.
    
    Provides automatic memory-based throttling.
    
    Usage:
        class MyService(MemoryAwareMixin):
            def __init__(self):
                super().__init__(max_workers=10)
                
            async def process(self, item):
                async with self.memory_slot():
                    # Do work
                    pass
    """
    
    def __init__(
        self,
        max_workers: int = 10,
        memory_thresholds: Optional[MemoryThresholds] = None
    ):
        self._max_workers = max_workers
        self._current_workers = max_workers
        self._semaphore = asyncio.Semaphore(max_workers)
        
        # Setup memory monitor
        self._memory_monitor = MemoryMonitor(thresholds=memory_thresholds)
        self._memory_monitor.register_callback(self._on_memory_event)
    
    async def start_monitoring(self):
        """Start memory monitoring."""
        await self._memory_monitor.start()
    
    def stop_monitoring(self):
        """Stop memory monitoring."""
        self._memory_monitor.stop()
    
    def _on_memory_event(self, level: str, stats: MemoryStats):
        """Handle memory events by adjusting worker count."""
        if level == "critical":
            old_workers = self._current_workers
            self._current_workers = max(1, self._current_workers // 2)
            self._semaphore = asyncio.Semaphore(self._current_workers)
            logger.warning(
                f"Reduced workers: {old_workers} -> {self._current_workers} "
                f"due to memory pressure"
            )
    
    @asynccontextmanager
    async def memory_slot(self):
        """Acquire a slot with memory awareness."""
        # Check if we should accept work
        if not self._memory_monitor.should_accept_work():
            raise MemoryError("Memory pressure too high, work rejected")
        
        async with self._semaphore:
            yield


# Global memory monitor instance
_global_monitor: Optional[MemoryMonitor] = None
_monitor_lock = asyncio.Lock()


async def get_memory_monitor(
    thresholds: Optional[MemoryThresholds] = None,
    **kwargs
) -> MemoryMonitor:
    """Get or create global memory monitor."""
    global _global_monitor
    
    async with _monitor_lock:
        if _global_monitor is None:
            _global_monitor = MemoryMonitor(thresholds=thresholds, **kwargs)
            await _global_monitor.start()
        
        return _global_monitor


def stop_global_monitor() -> None:
    """Stop global memory monitor."""
    global _global_monitor
    
    if _global_monitor:
        _global_monitor.stop()
        _global_monitor = None
