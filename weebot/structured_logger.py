"""Structured logging system for production environments."""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any, Optional
from datetime import datetime
from dataclasses import dataclass


@dataclass
class LogConfig:
    """Configuration for structured logging."""
    log_dir: Path = Path("logs")
    app_name: str = "weebot"
    environment: str = "development"  # development, staging, production
    log_level: str = "INFO"
    max_bytes: int = 10 * 1024 * 1024  # 10 MB
    backup_count: int = 5
    enable_console: bool = True
    enable_file: bool = True
    enable_json: bool = True
    sensitive_keys: set[str] | None = None


class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive data in log records."""
    
    DEFAULT_SENSITIVE_KEYS = {
        'password', 'secret', 'token', 'api_key', 'apikey',
        'authorization', 'auth', 'key', 'private_key', 'credentials',
        'kimi_api_key', 'openai_api_key', 'anthropic_api_key',
        'deepseek_api_key', 'telegram_bot_token', 'slack_webhook_url',
    }
    
    def __init__(self, sensitive_keys: set[str] | None = None):
        super().__init__()
        self.sensitive_keys = sensitive_keys or self.DEFAULT_SENSITIVE_KEYS
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Mask sensitive data in the log record."""
        # Check if record has extra fields
        for key in self.sensitive_keys:
            if hasattr(record, key):
                value = getattr(record, key)
                if value and isinstance(value, str):
                    masked = self._mask_value(value)
                    setattr(record, key, masked)
        
        # Also check the message if it's a dict/string
        if isinstance(record.msg, dict):
            record.msg = self._mask_dict(record.msg)
        elif isinstance(record.args, dict):
            record.args = self._mask_dict(record.args)
        
        return True
    
    def _mask_value(self, value: str) -> str:
        """Mask a sensitive value."""
        if len(value) <= 8:
            return "***"
        return value[:4] + "***" + value[-4:]
    
    def _mask_dict(self, data: dict) -> dict:
        """Recursively mask sensitive values in a dictionary."""
        result = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(s in key_lower for s in self.sensitive_keys):
                if isinstance(value, str):
                    result[key] = self._mask_value(value)
                else:
                    result[key] = "***"
            elif isinstance(value, dict):
                result[key] = self._mask_dict(value)
            elif isinstance(value, list):
                result[key] = self._mask_list(value)
            else:
                result[key] = value
        return result
    
    def _mask_list(self, data: list) -> list:
        """Recursively mask sensitive values in a list."""
        result = []
        for item in data:
            if isinstance(item, dict):
                result.append(self._mask_dict(item))
            elif isinstance(item, list):
                result.append(self._mask_list(item))
            else:
                result.append(item)
        return result


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def __init__(self, app_name: str = "weebot", environment: str = "development"):
        super().__init__()
        self.app_name = app_name
        self.environment = environment
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "app": self.app_name,
            "environment": self.environment,
            "source": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add any extra fields
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                'thread', 'threadName', 'processName', 'process', 'getMessage',
            }:
                log_data[key] = value
        
        return json.dumps(log_data, default=str)


class StructuredLogger:
    """
    Production-ready structured logging system.
    
    Features:
    - JSON structured logs for production
    - Human-readable format for development
    - Automatic log rotation
    - Sensitive data masking
    - Contextual logging support
    """
    
    def __init__(self, config: Optional[LogConfig] = None):
        self.config = config or LogConfig()
        self._loggers: dict[str, logging.Logger] = {}
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """Configure the logging system."""
        # Ensure log directory exists
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Root logger configuration
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.log_level.upper()))
        
        # Remove existing handlers to avoid duplicates
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Add handlers
        if self.config.enable_console:
            console_handler = self._create_console_handler()
            root_logger.addHandler(console_handler)
        
        if self.config.enable_file:
            if self.config.enable_json:
                json_handler = self._create_json_handler()
                root_logger.addHandler(json_handler)
            else:
                file_handler = self._create_file_handler()
                root_logger.addHandler(file_handler)
        
        # Add sensitive data filter
        sensitive_filter = SensitiveDataFilter(self.config.sensitive_keys)
        root_logger.addFilter(sensitive_filter)
    
    def _create_console_handler(self) -> logging.Handler:
        """Create human-readable console handler."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, self.config.log_level.upper()))
        
        if self.config.environment == "production":
            # Simple format for production console
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            )
        else:
            # Detailed format for development
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)-20s | %(filename)s:%(lineno)d | %(message)s"
            )
        
        handler.setFormatter(formatter)
        return handler
    
    def _create_file_handler(self) -> logging.Handler:
        """Create plain text file handler with rotation."""
        log_file = self.config.log_dir / f"{self.config.app_name}.log"
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self.config.max_bytes,
            backupCount=self.config.backup_count,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-20s | %(filename)s:%(lineno)d | %(message)s"
        )
        handler.setFormatter(formatter)
        return handler
    
    def _create_json_handler(self) -> logging.Handler:
        """Create JSON structured log handler."""
        log_file = self.config.log_dir / f"{self.config.app_name}.json.log"
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self.config.max_bytes,
            backupCount=self.config.backup_count,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        
        formatter = JSONFormatter(
            app_name=self.config.app_name,
            environment=self.config.environment,
        )
        handler.setFormatter(formatter)
        return handler
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger with the specified name."""
        if name not in self._loggers:
            logger = logging.getLogger(name)
            self._loggers[name] = logger
        return self._loggers[name]
    
    def bind_context(self, **context) -> logging.LoggerAdapter:
        """
        Create a logger adapter with bound context.
        
        Usage:
            logger = structured_logger.bind_context(request_id="abc", user_id="123")
            logger.info("Processing request")  # Includes request_id and user_id in logs
        """
        logger = logging.getLogger("weebot")
        return logging.LoggerAdapter(logger, context)


# Global instance
_global_logger: Optional[StructuredLogger] = None


def get_structured_logger(config: Optional[LogConfig] = None) -> StructuredLogger:
    """Get or create global structured logger."""
    global _global_logger
    if _global_logger is None:
        _global_logger = StructuredLogger(config)
    return _global_logger


def get_logger(name: str) -> logging.Logger:
    """Convenience function to get a logger."""
    return get_structured_logger().get_logger(name)


def configure_logging(environment: str = "development", log_level: str = "INFO") -> None:
    """
    Quick configuration for common environments.
    
    Usage:
        configure_logging(environment="production", log_level="WARNING")
    """
    config = LogConfig(
        environment=environment,
        log_level=log_level,
        enable_json=(environment == "production"),
    )
    get_structured_logger(config)


class LogContext:
    """
    Context manager for temporary log context.
    
    Usage:
        with LogContext(request_id=req_id, operation="process"):
            logger.info("Starting")  # Automatically includes context
    """
    
    def __init__(self, **kwargs):
        self.context = kwargs
        self._adapter = None
    
    def __enter__(self):
        self._adapter = get_structured_logger().bind_context(**self.context)
        return self._adapter
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
