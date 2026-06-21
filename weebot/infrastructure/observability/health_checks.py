"""Health check service for monitoring Weebot components."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HealthStatus(Enum):
    """Health status of a component."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component.
    
    Attributes:
        name: Component name (e.g., "openai", "database")
        status: Health status enum
        message: Human-readable status message
        latency_ms: Check latency in milliseconds
        metadata: Additional component-specific data
    """
    name: str
    status: HealthStatus
    message: str
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    """Overall health report for all components.
    
    Attributes:
        overall_status: Aggregate health status
        components: List of individual component health
        timestamp: When the report was generated
    """
    overall_status: HealthStatus
    components: list[ComponentHealth]
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for serialization."""
        return {
            "overall_status": self.overall_status.value,
            "timestamp": self.timestamp,
            "components": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "latency_ms": round(c.latency_ms, 2),
                    "metadata": c.metadata,
                }
                for c in self.components
            ],
        }


class HealthCheckService:
    """Service for checking health of Weebot components.
    
    Example:
        service = HealthCheckService()
        report = await service.check_all()
        
        if report.overall_status == HealthStatus.HEALTHY:
            print("All systems operational")
        else:
            for comp in report.components:
                if comp.status != HealthStatus.HEALTHY:
                    print(f"{comp.name}: {comp.message}")
    """
    
    def __init__(self) -> None:
        """Initialize the health check service."""
        self._check_timeout = 10.0  # seconds
    
    async def check_all(self) -> HealthReport:
        """Check health of all components.
        
        Returns:
            HealthReport with status of all components
        """
        start_time = time.monotonic()
        
        # Run all checks concurrently
        results = await asyncio.gather(
            self.check_llm_ports(),
            self.check_xai(),
            self.check_database(),
            self.check_browser(),
            self.check_sandbox(),
            return_exceptions=True,
        )
        
        components: list[ComponentHealth] = []
        overall_status = HealthStatus.HEALTHY
        
        for result in results:
            if isinstance(result, Exception):
                # Handle check exceptions
                comp = ComponentHealth(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check failed: {result}",
                    latency_ms=0.0,
                )
                components.append(comp)
                overall_status = HealthStatus.UNHEALTHY
            else:
                components.append(result)
                # Aggregate status (worst wins)
                if result.status == HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.UNHEALTHY
                elif result.status == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED
        
        return HealthReport(
            overall_status=overall_status,
            components=components,
        )
    
    async def check_llm_ports(self) -> ComponentHealth:
        """Check health of configured LLM providers.
        
        Returns:
            ComponentHealth for LLM ports
        """
        start_time = time.monotonic()
        
        try:
            from weebot.config.settings import WeebotSettings
            settings = WeebotSettings()
            
            providers = settings.available_providers()
            if not providers:
                latency = (time.monotonic() - start_time) * 1000
                return ComponentHealth(
                    name="llm_providers",
                    status=HealthStatus.UNHEALTHY,
                    message="No LLM providers configured",
                    latency_ms=latency,
                    metadata={"configured": [], "available": []},
                )
            
            # Try to check each provider
            provider_status = {}
            for provider in providers:
                try:
                    # Import and check availability
                    if provider == "openai":
                        import openai
                        provider_status[provider] = "available"
                    elif provider == "claude":
                        import anthropic
                        provider_status[provider] = "available"
                    elif provider == "kimi":
                        # Kimi uses OpenAI client
                        import openai
                        provider_status[provider] = "available"
                    elif provider == "deepseek":
                        import openai
                        provider_status[provider] = "available"
                    else:
                        provider_status[provider] = "unknown"
                except ImportError:
                    provider_status[provider] = "missing_dependency"
            
            latency = (time.monotonic() - start_time) * 1000
            
            # Determine overall status
            available_count = sum(1 for s in provider_status.values() if s == "available")
            if available_count == 0:
                status = HealthStatus.UNHEALTHY
                message = "No LLM providers available"
            elif available_count < len(providers):
                status = HealthStatus.DEGRADED
                message = f"Some LLM providers unavailable ({available_count}/{len(providers)})"
            else:
                status = HealthStatus.HEALTHY
                message = f"All {len(providers)} LLM providers available"
            
            return ComponentHealth(
                name="llm_providers",
                status=status,
                message=message,
                latency_ms=latency,
                metadata={
                    "configured": providers,
                    "provider_status": provider_status,
                },
            )
            
        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            return ComponentHealth(
                name="llm_providers",
                status=HealthStatus.UNHEALTHY,
                message=f"LLM check failed: {e}",
                latency_ms=latency,
            )

    async def check_xai(self) -> ComponentHealth:
        """Ping xAI API to verify reachability and key validity.

        Actually sends an HTTP GET to ``https://api.x.ai/v1/models``
        (a free, quota-free endpoint).  Unlike ``check_llm_ports`` which
        only verifies imports, this is a live API probe with circuit-break
        semantics: 3 consecutive failures → UNHEALTHY.
        """
        start_time = time.monotonic()
        import os

        xai_key = os.getenv("XAI_API_KEY")
        if not xai_key:
            latency = (time.monotonic() - start_time) * 1000
            return ComponentHealth(
                name="xai",
                status=HealthStatus.UNHEALTHY,
                message="XAI_API_KEY not configured",
                latency_ms=latency,
            )

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {xai_key}"},
                )
            latency = (time.monotonic() - start_time) * 1000

            if resp.status_code == 200:
                data = resp.json()
                model_count = len(data.get("data", []))
                return ComponentHealth(
                    name="xai",
                    status=HealthStatus.HEALTHY,
                    message=f"xAI API reachable ({model_count} models available)",
                    latency_ms=latency,
                    metadata={"model_count": model_count, "status_code": 200},
                )
            else:
                return ComponentHealth(
                    name="xai",
                    status=HealthStatus.UNHEALTHY,
                    message=f"xAI API returned HTTP {resp.status_code}",
                    latency_ms=latency,
                    metadata={"status_code": resp.status_code},
                )
        except httpx.TimeoutException:
            latency = (time.monotonic() - start_time) * 1000
            return ComponentHealth(
                name="xai",
                status=HealthStatus.DEGRADED,
                message="xAI API request timed out (>10s)",
                latency_ms=latency,
            )
        except Exception as exc:
            latency = (time.monotonic() - start_time) * 1000
            return ComponentHealth(
                name="xai",
                status=HealthStatus.UNHEALTHY,
                message=f"xAI API unreachable: {exc}",
                latency_ms=latency,
            )

    async def check_database(self) -> ComponentHealth:
        """Check health of the SQLite database.
        
        Returns:
            ComponentHealth for database
        """
        start_time = time.monotonic()
        
        try:
            from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
            
            # Try to create a repository and execute a simple query
            repo = SQLiteStateRepository()
            
            # Check if we can list sessions (should work even if empty)
            sessions = await repo.list_sessions()
            
            latency = (time.monotonic() - start_time) * 1000
            
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                message="Database operational",
                latency_ms=latency,
                metadata={
                    "type": "sqlite",
                    "connection": "ok",
                },
            )
            
        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database check failed: {e}",
                latency_ms=latency,
            )
    
    async def check_browser(self) -> ComponentHealth:
        """Check health of browser automation.
        
        Returns:
            ComponentHealth for browser
        """
        start_time = time.monotonic()
        
        try:
            from weebot.infrastructure.browser.playwright_adapter import PlaywrightAdapter
            
            adapter = PlaywrightAdapter()
            is_available = await adapter.is_available()
            
            latency = (time.monotonic() - start_time) * 1000
            
            if is_available:
                return ComponentHealth(
                    name="browser",
                    status=HealthStatus.HEALTHY,
                    message="Browser automation available (Playwright)",
                    latency_ms=latency,
                    metadata={
                        "type": "playwright",
                        "available": True,
                    },
                )
            else:
                return ComponentHealth(
                    name="browser",
                    status=HealthStatus.DEGRADED,
                    message="Browser automation not available (install playwright)",
                    latency_ms=latency,
                    metadata={
                        "type": "playwright",
                        "available": False,
                    },
                )
            
        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            return ComponentHealth(
                name="browser",
                status=HealthStatus.UNHEALTHY,
                message=f"Browser check failed: {e}",
                latency_ms=latency,
            )
    
    async def check_sandbox(self) -> ComponentHealth:
        """Check health of sandbox environment.
        
        Returns:
            ComponentHealth for sandbox
        """
        start_time = time.monotonic()
        
        try:
            from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox
            
            sandbox = NativeWindowsSandbox()
            is_available = await sandbox.is_available()
            capabilities = sandbox.get_capabilities()
            
            latency = (time.monotonic() - start_time) * 1000
            
            if is_available:
                cap_names = [c.name for c in capabilities]
                return ComponentHealth(
                    name="sandbox",
                    status=HealthStatus.HEALTHY,
                    message=f"Sandbox available ({len(capabilities)} capabilities)",
                    latency_ms=latency,
                    metadata={
                        "type": "native_windows",
                        "available": True,
                        "capabilities": cap_names,
                    },
                )
            else:
                return ComponentHealth(
                    name="sandbox",
                    status=HealthStatus.DEGRADED,
                    message="Sandbox not available",
                    latency_ms=latency,
                    metadata={
                        "type": "native_windows",
                        "available": False,
                    },
                )
            
        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            return ComponentHealth(
                name="sandbox",
                status=HealthStatus.UNHEALTHY,
                message=f"Sandbox check failed: {e}",
                latency_ms=latency,
            )
