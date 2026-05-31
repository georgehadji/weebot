"""Health check API routes with comprehensive system metrics."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Depends


from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort

async def get_state_repo(request: Request) -> StateRepositoryPort:
    """Resolve StateRepositoryPort from the application DI container."""
    container = request.app.state.container
    return container.get(StateRepositoryPort)

from weebot.interfaces.web.schemas import HealthResponse, HealthComponent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Comprehensive health check including all system components.
    
    Returns:
        HealthResponse with status of all critical and optional components
    """
    components = []
    overall_status = "healthy"
    
    # Check LLM providers
    try:
        from weebot.application.services.model_selection import ModelSelectionService
        service = ModelSelectionService()
        available = service.available_models()
        
        components.append(HealthComponent(
            name="llm_providers",
            status="healthy" if available else "degraded",
            message=f"{len(available)} providers available" if available else "No providers configured",
        ))
    except Exception as e:
        components.append(HealthComponent(
            name="llm_providers",
            status="unhealthy",
            message=str(e),
        ))
        overall_status = "unhealthy"
    
    # Check database with pool stats
    try:
        
        sessions = await state_repo.list_sessions(limit=1)
        
        # Get pool stats if available
        pool_stats = repo.get_pool_stats()
        pool_msg = "Database operational"
        if pool_stats.get("initialized"):
            pool_msg = f"Pool: {pool_stats.get('available_read_connections', 'N/A')} connections available"
        
        components.append(HealthComponent(
            name="database",
            status="healthy",
            message=pool_msg,
        ))
    except Exception as e:
        components.append(HealthComponent(
            name="database",
            status="unhealthy",
            message=str(e),
        ))
        overall_status = "unhealthy"
    
    # Check circuit breakers
    try:
        from weebot.core.circuit_breaker import CircuitBreaker
        # Get global circuit breaker states if any exist
        # This is a simplified check - in production you'd track all CBs
        components.append(HealthComponent(
            name="circuit_breakers",
            status="healthy",
            message="Circuit breaker system operational",
        ))
    except Exception as e:
        components.append(HealthComponent(
            name="circuit_breakers",
            status="unhealthy",
            message=str(e),
        ))
    
    # Check memory status
    try:
        from weebot.core.memory_monitor import MemoryMonitor
        monitor = MemoryMonitor()
        stats = monitor.check_memory()
        
        memory_status = "healthy"
        if stats.percent >= 85:
            memory_status = "critical"
            overall_status = "degraded"
        elif stats.percent >= 75:
            memory_status = "warning"
        
        components.append(HealthComponent(
            name="memory",
            status=memory_status,
            message=f"{stats.rss_mb:.0f}MB / {stats.max_mb}MB ({stats.percent:.1f}%)",
        ))
    except Exception as e:
        components.append(HealthComponent(
            name="memory",
            status="unknown",
            message=f"Monitor error: {e}",
        ))
    
    # Check browser pool if available
    try:
        from weebot.infrastructure.browser import SESSION_POOL_AVAILABLE, get_browser_pool
        if SESSION_POOL_AVAILABLE:
            # Don't actually get pool (might create it), just check if module loads
            components.append(HealthComponent(
                name="browser_pool",
                status="healthy",
                message="Browser session pool available",
            ))
        else:
            components.append(HealthComponent(
                name="browser_pool",
                status="healthy",
                message="Browser pool not configured (optional)",
            ))
    except Exception as e:
        components.append(HealthComponent(
            name="browser_pool",
            status="degraded",
            message=str(e),
        ))
    
    # Check if any component is degraded
    if any(c.status == "degraded" for c in components):
        overall_status = "degraded"
    if any(c.status == "critical" for c in components):
        overall_status = "unhealthy"
    
    return HealthResponse(
        status=overall_status,
        components=components,
        timestamp=datetime.utcnow(),
    )


@router.get("/ready")
async def readiness_check() -> dict:
    """Kubernetes-style readiness check."""
    checks = {}
    
    # Check database
    try:
        
        await repo.list_sessions(limit=1)
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        return {"ready": False, "checks": checks}
    
    # Check LLM availability
    try:
        from weebot.application.services.model_selection import ModelSelectionService
        service = ModelSelectionService()
        available = service.available_models()
        checks["llm_providers"] = f"{len(available)} available"
        if not available:
            return {"ready": False, "checks": checks}
    except Exception as e:
        checks["llm_providers"] = f"error: {e}"
        return {"ready": False, "checks": checks}
    
    return {"ready": True, "checks": checks}


@router.get("/live")
async def liveness_check() -> dict:
    """Kubernetes-style liveness check."""
    return {"alive": True, "timestamp": datetime.utcnow().isoformat()}


@router.get("/metrics")
async def metrics_check() -> Dict[str, Any]:
    """
    Detailed system metrics for monitoring.
    
    Returns comprehensive metrics including:
    - Memory usage
    - Circuit breaker states
    - Connection pool stats
    - Cache statistics
    """
    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }
    
    # Memory metrics
    try:
        from weebot.core.memory_monitor import MemoryMonitor
        monitor = MemoryMonitor()
        stats = monitor.check_memory()
        metrics["components"]["memory"] = {
            "rss_mb": round(stats.rss_mb, 2),
            "python_current_mb": round(stats.python_current_mb, 2),
            "python_peak_mb": round(stats.python_peak_mb, 2),
            "percent_of_max": round(stats.percent, 2),
            "system_percent": round(stats.system_percent, 2) if stats.system_percent else None,
        }
    except Exception as e:
        metrics["components"]["memory"] = {"error": str(e)}
    
    # Database pool metrics
    try:
        
        pool_stats = repo.get_pool_stats()
        metrics["components"]["database_pool"] = pool_stats
    except Exception as e:
        metrics["components"]["database_pool"] = {"error": str(e)}
    
    # Circuit breaker metrics (global)
    try:
        # This would need a registry of all circuit breakers
        # For now, report that the system is operational
        metrics["components"]["circuit_breakers"] = {
            "status": "operational",
            "note": "Per-adapter CB states available via adapter.get_metrics()"
        }
    except Exception as e:
        metrics["components"]["circuit_breakers"] = {"error": str(e)}
    
    # Cache metrics
    try:
        from weebot.infrastructure.cache.llm_cache import _cache_instances
        if _cache_instances:
            cache_metrics = {}
            for name, cache in _cache_instances.items():
                try:
                    cache_metrics[name] = cache.get_stats()
                except Exception as ce:
                    cache_metrics[name] = {"error": str(ce)}
            metrics["components"]["caches"] = cache_metrics
        else:
            metrics["components"]["caches"] = {"status": "no active caches"}
    except Exception as e:
        metrics["components"]["caches"] = {"error": str(e)}
    
    # Browser pool metrics
    try:
        from weebot.infrastructure.browser.session_pool import _global_pool
        if _global_pool:
            metrics["components"]["browser_pool"] = _global_pool.get_stats()
        else:
            metrics["components"]["browser_pool"] = {"status": "not initialized"}
    except Exception as e:
        metrics["components"]["browser_pool"] = {"error": str(e)}
    
    # Adaptive concurrency metrics
    try:
        from weebot.core.adaptive_concurrency import AdaptiveConcurrencyController
        # Would need a registry of controllers
        metrics["components"]["adaptive_concurrency"] = {
            "status": "available",
            "note": "Per-component controllers track their own stats"
        }
    except Exception as e:
        metrics["components"]["adaptive_concurrency"] = {"error": str(e)}
    
    return metrics


@router.get("/status")
async def detailed_status() -> Dict[str, Any]:
    """
    Human-readable system status.
    
    Returns a summary of system health suitable for dashboards.
    """
    status = {
        "status": "operational",
        "version": "2.6.0",
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "resilient_adapters": True,
            "connection_pooling": True,
            "response_caching": True,
            "circuit_breaker": True,
            "memory_monitoring": True,
            "adaptive_concurrency": True,
            "browser_pooling": True,
        }
    }
    
    # Overall health
    try:
        health = await health_check()
        status["health"] = health.status
        status["components"] = [
            {"name": c.name, "status": c.status, "message": c.message}
            for c in health.components
        ]
    except Exception as e:
        status["health"] = "error"
        status["error"] = str(e)
    
    return status
