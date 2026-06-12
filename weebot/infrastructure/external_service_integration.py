"""
External Service Integration for Weebot

This module provides capabilities for integrating with external services
and APIs to extend Weebot's functionality.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Callable, Awaitable
from datetime import datetime, timedelta
import aiohttp
import logging
from abc import ABC, abstractmethod

from weebot.core.circuit_breaker import CircuitBreaker
from weebot.tools.base import ToolResult


class ServiceType(Enum):
    """Types of external services that can be integrated."""
    API = "api"
    DATABASE = "database"
    MESSAGE_QUEUE = "message_queue"
    STORAGE = "storage"
    AUTHENTICATION = "authentication"
    PAYMENT = "payment"
    NOTIFICATION = "notification"
    MONITORING = "monitoring"
    CUSTOM = "custom"


class ServiceStatus(Enum):
    """Status of an external service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"


@dataclass
class ServiceConfig:
    """Configuration for an external service."""
    name: str
    service_type: ServiceType
    base_url: str
    api_key: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30
    retry_attempts: int = 3
    circuit_breaker_config: Optional[Dict[str, Any]] = None
    rate_limit_config: Optional[Dict[str, Any]] = None
    enabled: bool = True


@dataclass
class ServiceResponse:
    """Response from an external service."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    headers: Optional[Dict[str, str]] = None
    execution_time_ms: Optional[float] = None


class ExternalService(ABC):
    """Abstract base class for external services."""
    
    def __init__(self, config: ServiceConfig, circuit_breaker: Optional[CircuitBreaker] = None):
        self.config = config
        self.circuit_breaker = circuit_breaker
        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._initialized = False
    
    async def initialize(self):
        """Initialize the service connection."""
        if not self._initialized:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            )
            self._initialized = True
    
    async def shutdown(self):
        """Shutdown the service connection."""
        if self.session:
            await self.session.close()
            self.session = None
        self._initialized = False
    
    @abstractmethod
    async def execute(self, operation: str, **kwargs) -> ServiceResponse:
        """Execute an operation on the external service."""
        pass
    
    async def health_check(self) -> ServiceStatus:
        """Check the health of the external service."""
        try:
            response = await self.execute("health_check")
            if response.success:
                return ServiceStatus.HEALTHY
            else:
                return ServiceStatus.UNAVAILABLE
        except Exception:
            return ServiceStatus.UNAVAILABLE


class APIService(ExternalService):
    """Generic API service integration."""
    
    async def execute(self, operation: str, **kwargs) -> ServiceResponse:
        """Execute an API operation."""
        if not self.config.enabled:
            return ServiceResponse(
                success=False,
                error="Service is disabled",
                status_code=503
            )
        
        if not self.session:
            await self.initialize()
        
        start_time = datetime.now()
        
        # Construct URL based on operation
        url = f"{self.config.base_url.rstrip('/')}/{operation.lstrip('/')}"
        
        # Prepare headers
        headers = self.config.headers or {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        
        # Add any additional headers from kwargs
        if "headers" in kwargs:
            headers.update(kwargs["headers"])
        
        # Prepare request data
        method = kwargs.get("method", "GET").upper()
        json_data = kwargs.get("json", None)
        params = kwargs.get("params", None)
        
        # Check circuit breaker if available
        if self.circuit_breaker:
            entity_id = f"{self.config.name}:{operation}"
            breaker_result = await self.circuit_breaker.evaluate(entity_id)
            if not breaker_result.allowed:
                return ServiceResponse(
                    success=False,
                    error=f"Circuit breaker open: {breaker_result.reason}",
                    status_code=503
                )
        
        # Execute request with retry logic
        for attempt in range(self.config.retry_attempts):
            try:
                async with self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params
                ) as response:
                    response_text = await response.text()
                    response_headers = dict(response.headers)
                    
                    execution_time = (datetime.now() - start_time).total_seconds() * 1000
                    
                    if response.status == 200:
                        try:
                            response_data = json.loads(response_text) if response_text else None
                        except json.JSONDecodeError:
                            response_data = response_text
                        
                        # Record success in circuit breaker
                        if self.circuit_breaker:
                            await self.circuit_breaker.record_success(entity_id)
                        
                        return ServiceResponse(
                            success=True,
                            data=response_data,
                            status_code=response.status,
                            headers=response_headers,
                            execution_time_ms=execution_time
                        )
                    else:
                        error_msg = f"HTTP {response.status}: {response_text}"
                        
                        # Record failure in circuit breaker
                        if self.circuit_breaker:
                            await self.circuit_breaker.record_failure(entity_id)
                        
                        is_client_error = 400 <= response.status < 500
                        if attempt < self.config.retry_attempts - 1 and not is_client_error:
                            # Wait before retry (4xx client errors are never retried)
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            continue
                        else:
                            return ServiceResponse(
                                success=False,
                                error=error_msg,
                                status_code=response.status,
                                headers=response_headers,
                                execution_time_ms=execution_time
                            )
            
            except asyncio.TimeoutError:
                error_msg = f"Request timed out after {self.config.timeout}s"
                
                # Record failure in circuit breaker
                if self.circuit_breaker:
                    await self.circuit_breaker.record_failure(entity_id)
                
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    return ServiceResponse(
                        success=False,
                        error=error_msg,
                        execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000
                    )
            
            except Exception as e:
                error_msg = f"Request failed: {str(e)}"
                
                # Record failure in circuit breaker
                if self.circuit_breaker:
                    await self.circuit_breaker.record_failure(entity_id)
                
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    return ServiceResponse(
                        success=False,
                        error=error_msg,
                        execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000
                    )
        
        # This shouldn't be reached, but just in case
        return ServiceResponse(
            success=False,
            error="Unexpected error in API service execution",
            execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000
        )


class ServiceRegistry:
    """Registry for managing external services."""
    
    def __init__(self):
        self.services: Dict[str, ExternalService] = {}
        self.circuit_breaker = CircuitBreaker()
        self.logger = logging.getLogger(f"{__name__}.ServiceRegistry")
    
    async def register_service(self, name: str, service: ExternalService):
        """Register an external service."""
        self.services[name] = service
        await service.initialize()
        self.logger.info(f"Registered service: {name}")
    
    async def unregister_service(self, name: str):
        """Unregister an external service."""
        if name in self.services:
            service = self.services[name]
            await service.shutdown()
            del self.services[name]
            self.logger.info(f"Unregistered service: {name}")
    
    async def get_service(self, name: str) -> Optional[ExternalService]:
        """Get a registered service by name."""
        return self.services.get(name)
    
    async def execute_service_operation(
        self, 
        service_name: str, 
        operation: str, 
        **kwargs
    ) -> ServiceResponse:
        """Execute an operation on a registered service."""
        service = await self.get_service(service_name)
        if not service:
            return ServiceResponse(
                success=False,
                error=f"Service '{service_name}' not found",
                status_code=404
            )
        
        return await service.execute(operation, **kwargs)
    
    async def health_check_all(self) -> Dict[str, ServiceStatus]:
        """Check the health of all registered services."""
        health_status = {}
        for name, service in self.services.items():
            try:
                status = await service.health_check()
                health_status[name] = status
            except Exception as e:
                self.logger.error(f"Error checking health of service {name}: {e}")
                health_status[name] = ServiceStatus.UNAVAILABLE
        
        return health_status
    
    async def shutdown_all(self):
        """Shutdown all registered services."""
        for name, service in self.services.items():
            try:
                await service.shutdown()
            except Exception as e:
                self.logger.error(f"Error shutting down service {name}: {e}")


class ServiceIntegrationTool:
    """Tool for integrating with external services."""
    
    def __init__(self, service_registry: ServiceRegistry):
        self.service_registry = service_registry
        self.logger = logging.getLogger(f"{__name__}.ServiceIntegrationTool")
    
    async def call_external_service(
        self,
        service_name: str,
        operation: str,
        **kwargs
    ) -> ToolResult:
        """Call an external service and return a tool result."""
        try:
            response = await self.service_registry.execute_service_operation(
                service_name, operation, **kwargs
            )
            
            if response.success:
                return ToolResult(
                    content=json.dumps(response.data, indent=2) if response.data else "Operation completed successfully",
                    tool_error=False
                )
            else:
                return ToolResult(
                    content=f"Service call failed: {response.error}",
                    tool_error=True
                )
        except Exception as e:
            self.logger.error(f"Error calling external service {service_name}: {e}")
            return ToolResult(
                content=f"Error calling external service: {str(e)}",
                tool_error=True
            )
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "call_external_service",
                "description": "Call an external service API",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Name of the registered service to call"
                        },
                        "operation": {
                            "type": "string",
                            "description": "Operation to perform on the service"
                        },
                        "kwargs": {
                            "type": "object",
                            "description": "Additional arguments for the operation"
                        }
                    },
                    "required": ["service_name", "operation"]
                }
            }
        }


# Factory function for creating common service types
def create_api_service(config: ServiceConfig) -> APIService:
    """Create an API service instance."""
    return APIService(config)


def create_database_service(config: ServiceConfig) -> ExternalService:
    """Create a database service instance."""
    # This would be implemented based on specific database needs
    raise NotImplementedError("Database service not yet implemented")


def create_notification_service(config: ServiceConfig) -> ExternalService:
    """Create a notification service instance."""
    # This would be implemented based on specific notification needs
    raise NotImplementedError("Notification service not yet implemented")


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # Create a service registry
        registry = ServiceRegistry()
        
        # Create a configuration for a test API service
        api_config = ServiceConfig(
            name="test_api",
            service_type=ServiceType.API,
            base_url="https://httpbin.org",
            timeout=10,
            retry_attempts=2
        )
        
        # Create and register an API service
        api_service = create_api_service(api_config)
        await registry.register_service("test_api", api_service)
        
        # Execute an operation
        print("Testing external service integration...")
        response = await registry.execute_service_operation(
            "test_api",
            "get",
            method="GET",
            params={"key": "value"}
        )
        
        print(f"Response success: {response.success}")
        print(f"Response data: {response.data}")
        print(f"Status code: {response.status_code}")
        print(f"Execution time: {response.execution_time_ms}ms")
        
        # Check health of all services
        health_status = await registry.health_check_all()
        print(f"Service health: {health_status}")
        
        # Shutdown services
        await registry.shutdown_all()
        print("Services shut down")
    
    asyncio.run(example())