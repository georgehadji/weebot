"""Adaptive concurrency control based on system load."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, AsyncContextManager

logger = logging.getLogger(__name__)

# Optional psutil for system metrics
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


@dataclass
class ConcurrencyLimits:
    """Concurrency limit configuration."""
    min_workers: int = 2
    max_workers: int = 20
    cpu_threshold: float = 75.0  # Scale down above this
    memory_threshold: float = 80.0  # Scale down above this


class AdaptiveConcurrencyController:
    """
    Dynamically adjust concurrency based on system load.
    
    Monitors CPU and memory usage, automatically scaling worker count
    up or down to maintain optimal performance without overwhelming
    the system.
    
    Usage:
        controller = AdaptiveConcurrencyController(
            min_workers=2,
            max_workers=20,
            cpu_threshold=75.0
        )
        
        # Start background adjustment
        await controller.start()
        
        # Use slots for work
        async with controller.slot():
            await do_work()
        
        # Get current limits
        print(f"Current workers: {controller.current_workers}")
    
    Attributes:
        min_workers: Minimum concurrent workers
        max_workers: Maximum concurrent workers
        current_workers: Current (adjusted) worker count
    """
    
    def __init__(
        self,
        min_workers: int = 2,
        max_workers: int = 20,
        cpu_threshold: float = 75.0,
        memory_threshold: float = 80.0,
        adjustment_interval: float = 30.0,
        scale_down_factor: float = 0.8,
        scale_up_increment: int = 1
    ):
        """
        Initialize adaptive concurrency controller.
        
        Args:
            min_workers: Minimum concurrent workers
            max_workers: Maximum concurrent workers
            cpu_threshold: CPU % above which to scale down
            memory_threshold: Memory % above which to scale down
            adjustment_interval: Seconds between adjustments
            scale_down_factor: Multiply workers by this when scaling down
            scale_up_increment: Add this many workers when scaling up
        """
        self.min_workers = max(1, min_workers)
        self.max_workers = max(self.min_workers, max_workers)
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.adjustment_interval = adjustment_interval
        self.scale_down_factor = scale_down_factor
        self.scale_up_increment = scale_up_increment
        
        self.current_workers = self.min_workers
        # Semaphore is created once at max capacity and never replaced.
        # Replacing it (as the old code did) orphans any coroutines
        # blocked on acquire() — they wait forever on the discarded
        # semaphore while release() operates on the new one.
        self._semaphore = asyncio.Semaphore(self.max_workers)
        self._lock = asyncio.Lock()
        
        self._running = False
        self._adjustment_task: Optional[asyncio.Task] = None
        
        # Statistics
        self._stats = {
            "adjustments": 0,
            "scale_up_count": 0,
            "scale_down_count": 0,
            "current_cpu": 0.0,
            "current_memory": 0.0,
        }
        
        if not PSUTIL_AVAILABLE:
            logger.warning("psutil not available, adaptive concurrency disabled")
    
    async def start(self) -> None:
        """Start background adjustment loop."""
        if not PSUTIL_AVAILABLE:
            logger.warning("Cannot start: psutil not available")
            return
        
        if self._running:
            return
        
        self._running = True
        self._adjustment_task = asyncio.create_task(self._adjustment_loop())
        logger.info(
            f"Adaptive concurrency started: "
            f"workers={self.current_workers} (range: {self.min_workers}-{self.max_workers}), "
            f"thresholds: CPU>{self.cpu_threshold}%, Memory>{self.memory_threshold}%"
        )
    
    async def _adjustment_loop(self) -> None:
        """Background loop for adjusting concurrency."""
        while self._running:
            try:
                await self._adjust()
                await asyncio.sleep(self.adjustment_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Adjustment loop error: {e}")
                await asyncio.sleep(self.adjustment_interval)
    
    async def _adjust(self) -> None:
        """Adjust worker count based on system metrics."""
        # Get current metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent
        
        self._stats["current_cpu"] = cpu_percent
        self._stats["current_memory"] = memory_percent
        
        async with self._lock:
            old_workers = self.current_workers
            new_workers = old_workers
            
            # Determine if we need to scale
            high_cpu = cpu_percent > self.cpu_threshold
            high_memory = memory_percent > self.memory_threshold
            low_cpu = cpu_percent < (self.cpu_threshold - 20)
            low_memory = memory_percent < (self.memory_threshold - 10)
            
            if high_cpu or high_memory:
                # Scale down
                new_workers = max(
                    self.min_workers,
                    int(old_workers * self.scale_down_factor)
                )
                if new_workers < old_workers:
                    self._stats["scale_down_count"] += 1
                    logger.warning(
                        f"High load detected (CPU: {cpu_percent:.1f}%, "
                        f"Memory: {memory_percent:.1f}%), "
                        f"scaling down: {old_workers} -> {new_workers}"
                    )
            
            elif low_cpu and low_memory and old_workers < self.max_workers:
                # Scale up gradually
                new_workers = min(
                    self.max_workers,
                    old_workers + self.scale_up_increment
                )
                if new_workers > old_workers:
                    self._stats["scale_up_count"] += 1
                    logger.info(
                        f"Low load detected (CPU: {cpu_percent:.1f}%, "
                        f"Memory: {memory_percent:.1f}%), "
                        f"scaling up: {old_workers} -> {new_workers}"
                    )
            
            # Update if changed.  Scaling up: we already have max capacity
            # (the semaphore was created at max_workers).  Scaling down:
            # we record the advisory limit in current_workers but cannot
            # shrink the semaphore without orphaning blocked waiters.
            if new_workers != old_workers:
                self.current_workers = new_workers
                self._stats["adjustments"] += 1
    
    async def acquire(self) -> None:
        """Acquire a concurrency slot."""
        await self._semaphore.acquire()
    
    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()
    
    @asynccontextmanager
    async def slot(self):
        """Context manager for acquiring a concurrency slot."""
        await self.acquire()
        try:
            yield
        finally:
            self.release()
    
    def stop(self) -> None:
        """Stop the adjustment loop."""
        self._running = False
        
        if self._adjustment_task:
            self._adjustment_task.cancel()
            logger.info("Adaptive concurrency stopped")
    
    def get_stats(self) -> dict:
        """Get controller statistics."""
        return {
            "current_workers": self.current_workers,
            "min_workers": self.min_workers,
            "max_workers": self.max_workers,
            "running": self._running,
            **self._stats
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.stop()


class AdaptiveSemaphore:
    """
    Semaphore that adjusts its capacity based on load.
    
    Similar to AdaptiveConcurrencyController but as a standalone
    semaphore that can be used anywhere.
    
    Usage:
        sem = AdaptiveSemaphore(initial=5, min_value=1, max_value=20)
        await sem.start()
        
        async with sem:
            await do_work()
    """
    
    def __init__(
        self,
        initial: int = 5,
        min_value: int = 1,
        max_value: int = 20,
        adjustment_interval: float = 30.0
    ):
        self.min_value = min_value
        self.max_value = max_value
        self._initial = initial
        self.adjustment_interval = adjustment_interval
        
        self._semaphore = asyncio.Semaphore(max_value)
        self._controller: Optional[AdaptiveConcurrencyController] = None
    
    async def start(self) -> None:
        """Start adaptive adjustment."""
        if not PSUTIL_AVAILABLE:
            return
        
        self._controller = AdaptiveConcurrencyController(
            min_workers=self.min_value,
            max_workers=self.max_value,
            adjustment_interval=self.adjustment_interval
        )
        await self._controller.start()

    @property
    def current_value(self) -> int:
        """Current worker limit (reads from controller if started)."""
        if self._controller is not None:
            return self._controller.current_workers
        return self._initial
    
    async def acquire(self) -> None:
        """Acquire the semaphore."""
        await self._semaphore.acquire()
    
    def release(self) -> None:
        """Release the semaphore."""
        self._semaphore.release()
    
    def stop(self) -> None:
        """Stop adjustment."""
        if self._controller:
            self._controller.stop()
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()


# Convenience function for LLM request limiting
async def with_adaptive_limit(
    func,
    *args,
    controller: Optional[AdaptiveConcurrencyController] = None,
    **kwargs
):
    """
    Execute function with adaptive concurrency limit.
    
    Args:
        func: Async function to execute
        *args: Function arguments
        controller: Optional shared controller (creates new if None)
        **kwargs: Function keyword arguments
    
    Returns:
        Function result
    """
    if controller is None:
        controller = AdaptiveConcurrencyController()
        await controller.start()
        should_stop = True
    else:
        should_stop = False
    
    try:
        async with controller.slot():
            return await func(*args, **kwargs)
    finally:
        if should_stop:
            controller.stop()
