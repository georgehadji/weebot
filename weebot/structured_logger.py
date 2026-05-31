"""Structured Logging for Weebot Observability.

Phase 4 Implementation: JSON-formatted logs with correlation IDs,
performance tracking, and error categorization.

Features:
- JSON-formatted log output
- Correlation IDs across agents and workflows
- Performance tracking per tool and operation
- Error categorization with stack traces
- Contextual logging with automatic metadata

Usage:
    from weebot.structured_logger import StructuredLogger, get_logger
    
    logger = get_logger("agent.researcher")
    
    # Basic logging
    logger.info("Starting research", topic="AI Ethics")
    
    # With correlation ID
    with logger.correlation_id("workflow-123"):
        logger.info("Processing task", task_id="task-456")
        
    # Performance tracking
    with logger.timer("database_query"):
        results = db.query()
        
    # Error with categorization
    try:
        risky_operation()
    except Exception as e:
        logger.error(
            "Operation failed",
            error_type="runtime_error",
            error_category="CRITICAL",
            exc_info=True
        )
"""
from __future__ import annotations

import functools
import json
import logging
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable, Generator

# Context variables for correlation tracking
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
_agent_id: ContextVar[Optional[str]] = ContextVar("agent_id", default=None)
_workflow_id: ContextVar[Optional[str]] = ContextVar("workflow_id", default=None)


def _utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _utc_iso(ts: datetime) -> str:
    """Format datetime as UTC ISO-8601 with Z suffix."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.isoformat().replace("+00:00", "Z")


class StructuredLogRecord:
    """A structured log record that can be serialized to JSON."""
    
    def __init__(
        self,
        level: str,
        message: str,
        logger_name: str,
        timestamp: Optional[datetime] = None,
        correlation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        exc_info: Optional[str] = None,
        error_type: Optional[str] = None,
        error_category: Optional[str] = None,
        performance_data: Optional[Dict[str, Any]] = None,
    ):
        self.level = level
        self.message = message
        self.logger_name = logger_name
        self.timestamp = timestamp or _utc_now()
        self.correlation_id = correlation_id
        self.agent_id = agent_id
        self.workflow_id = workflow_id
        self.metadata = metadata or {}
        self.exc_info = exc_info
        self.error_type = error_type
        self.error_category = error_category
        self.performance_data = performance_data or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "timestamp": _utc_iso(self.timestamp),
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
        }
        
        # Add context IDs if present
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.agent_id:
            result["agent_id"] = self.agent_id
        if self.workflow_id:
            result["workflow_id"] = self.workflow_id
        
        # Add metadata
        if self.metadata:
            result["metadata"] = self.metadata
        
        # Add error information
        if self.error_type:
            result["error_type"] = self.error_type
        if self.error_category:
            result["error_category"] = self.error_category
        if self.exc_info:
            result["stack_trace"] = self.exc_info
        
        # Add performance data
        if self.performance_data:
            result["performance"] = self.performance_data
        
        return result
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class StructuredLogger:
    """
    Structured logger with correlation IDs and performance tracking.
    
    This logger provides:
    - JSON-formatted output
    - Automatic correlation ID tracking
    - Performance timing context managers
    - Error categorization
    """
    
    # Error categories for classification
    ERROR_CATEGORIES = {
        "CRITICAL": "System-critical errors requiring immediate attention",
        "ERROR": "Standard errors affecting functionality",
        "WARNING": "Warnings about potential issues",
        "VALIDATION": "Input validation errors",
        "TIMEOUT": "Operation timeout errors",
        "NETWORK": "Network-related errors",
        "PERMISSION": "Permission/access errors",
        "RESOURCE": "Resource exhaustion errors",
    }
    
    def __init__(self, name: str, level: int = logging.INFO):
        self.name = name
        self.level = level
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        
        # Add JSON handler if not already present
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JSONLogFormatter())
            self._logger.addHandler(handler)
    
    def _get_context(self) -> Dict[str, Optional[str]]:
        """Get current context from context variables."""
        return {
            "correlation_id": _correlation_id.get(),
            "agent_id": _agent_id.get(),
            "workflow_id": _workflow_id.get(),
        }
    
    def _log(
        self,
        level: str,
        message: str,
        exc_info: bool = False,
        error_type: Optional[str] = None,
        error_category: Optional[str] = None,
        **kwargs
    ):
        """Internal logging method."""
        context = self._get_context()
        
        # Capture exception info if requested
        exc_info_str = None
        if exc_info and sys.exc_info()[0]:
            exc_info_str = traceback.format_exc()
        
        # Build performance data from kwargs
        performance_data = {}
        perf_keys = ["duration_ms", "start_time", "end_time", "rows_affected", "bytes_processed"]
        for key in perf_keys:
            if key in kwargs:
                performance_data[key] = kwargs.pop(key)
        
        record = StructuredLogRecord(
            level=level,
            message=message,
            logger_name=self.name,
            correlation_id=context["correlation_id"],
            agent_id=context["agent_id"],
            workflow_id=context["workflow_id"],
            metadata=kwargs if kwargs else None,
            exc_info=exc_info_str,
            error_type=error_type,
            error_category=error_category,
            performance_data=performance_data if performance_data else None,
        )
        
        # Log via standard logging
        log_level = getattr(logging, level.upper())
        self._logger.log(log_level, record.to_json())
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log("DEBUG", message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log("INFO", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log("WARNING", message, error_category="WARNING", **kwargs)
    
    def error(
        self,
        message: str,
        error_type: Optional[str] = None,
        error_category: str = "ERROR",
        exc_info: bool = False,
        **kwargs
    ):
        """Log error message with categorization."""
        self._log(
            "ERROR",
            message,
            error_type=error_type,
            error_category=error_category,
            exc_info=exc_info,
            **kwargs
        )
    
    def critical(
        self,
        message: str,
        error_type: Optional[str] = None,
        exc_info: bool = False,
        **kwargs
    ):
        """Log critical message."""
        self._log(
            "CRITICAL",
            message,
            error_type=error_type,
            error_category="CRITICAL",
            exc_info=exc_info,
            **kwargs
        )
    
    @contextmanager
    def correlation_id(self, cid: Optional[str] = None) -> Generator[None, None, None]:
        """
        Context manager for correlation ID scope.
        
        Args:
            cid: Correlation ID (auto-generated if not provided)
        """
        token = _correlation_id.set(cid or str(uuid.uuid4()))
        try:
            yield
        finally:
            _correlation_id.reset(token)
    
    @contextmanager
    def agent_context(self, agent_id: str) -> Generator[None, None, None]:
        """Context manager for agent ID scope."""
        token = _agent_id.set(agent_id)
        try:
            yield
        finally:
            _agent_id.reset(token)
    
    @contextmanager
    def workflow_context(self, workflow_id: str) -> Generator[None, None, None]:
        """Context manager for workflow ID scope."""
        token = _workflow_id.set(workflow_id)
        try:
            yield
        finally:
            _workflow_id.reset(token)
    
    @contextmanager
    def timer(self, operation_name: str) -> Generator[None, None, None]:
        """
        Context manager for timing operations.
        
        Automatically logs performance data when context exits.
        """
        start_time = time.time()
        start_iso = _utc_iso(_utc_now())
        
        try:
            yield
            
            # Success - log timing
            duration_ms = (time.time() - start_time) * 1000
            self.info(
                f"Operation completed: {operation_name}",
                operation=operation_name,
                duration_ms=round(duration_ms, 2),
                start_time=start_iso,
                end_time=_utc_iso(_utc_now()),
                status="success"
            )
        except Exception as e:
            # Failure - log timing and error
            duration_ms = (time.time() - start_time) * 1000
            self.error(
                f"Operation failed: {operation_name}",
                operation=operation_name,
                duration_ms=round(duration_ms, 2),
                start_time=start_iso,
                end_time=_utc_iso(_utc_now()),
                status="failed",
                error_type=type(e).__name__,
                exc_info=True
            )
            raise
    
    def log_execution(
        self,
        func: Optional[Callable] = None,
        *,
        log_args: bool = False,
        log_result: bool = False
    ) -> Callable:
        """
        Decorator for logging function execution.
        
        Args:
            func: Function to decorate
            log_args: Whether to log function arguments
            log_result: Whether to log function result
        """
        def decorator(f: Callable) -> Callable:
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                func_name = f.__qualname__
                
                # Log entry
                entry_data = {"function": func_name}
                if log_args:
                    entry_data["args"] = str(args)
                    entry_data["kwargs"] = str(kwargs)
                
                self.info(f"Entering {func_name}", **entry_data)
                
                start_time = time.time()
                try:
                    result = f(*args, **kwargs)
                    
                    # Log success
                    duration_ms = (time.time() - start_time) * 1000
                    success_data = {
                        "function": func_name,
                        "duration_ms": round(duration_ms, 2),
                        "status": "success"
                    }
                    if log_result:
                        success_data["result"] = str(result)
                    
                    self.info(f"Completed {func_name}", **success_data)
                    return result
                    
                except Exception as e:
                    # Log failure
                    duration_ms = (time.time() - start_time) * 1000
                    self.error(
                        f"Failed {func_name}",
                        function=func_name,
                        duration_ms=round(duration_ms, 2),
                        status="failed",
                        error_type=type(e).__name__,
                        exc_info=True
                    )
                    raise
            
            return wrapper
        
        if func is None:
            return decorator
        return decorator(func)


class JSONLogFormatter(logging.Formatter):
    """Formatter that outputs JSON-structured logs."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # If the message is already a JSON string, pass it through
        if hasattr(record, "msg") and isinstance(record.msg, str):
            try:
                # Check if it's already JSON
                json.loads(record.msg)
                return record.msg
            except json.JSONDecodeError:
                pass
        
        # Otherwise, create a standard log record
        log_data = {
            "timestamp": _utc_iso(_utc_now()),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        if record.exc_info:
            log_data["stack_trace"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


# Module-level logger cache
_loggers: Dict[str, StructuredLogger] = {}


def get_logger(name: str) -> StructuredLogger:
    """Get or create a structured logger."""
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name)
    return _loggers[name]


def set_correlation_id(cid: str) -> None:
    """Set global correlation ID."""
    _correlation_id.set(cid)


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID."""
    return _correlation_id.get()


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())


# Convenience exports
__all__ = [
    "StructuredLogger",
    "StructuredLogRecord",
    "JSONLogFormatter",
    "get_logger",
    "set_correlation_id",
    "get_correlation_id",
    "generate_correlation_id",
]
