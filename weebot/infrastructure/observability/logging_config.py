"""Structured logging configuration — wraps stdlib logging with structlog.

Usage
-----
Call ``configure_logging()`` once at application startup (CLI or web entry point).
After that, all ``logging.getLogger(__name__)`` calls automatically produce
structured JSON output with bound context variables.

To bind per-request context::

    from structlog import get_logger, get_context
    log = structlog.get_logger()
    log = log.bind(session_id=session.id, flow_name="PlanActFlow")
    log.info("Flow started", step_count=5)

Dependencies
------------
- ``structlog>=25.1.0`` (already in requirements.txt)
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def configure_logging() -> None:
    """Configure structlog as the stdlib logging backend.

    Call once at startup.  After this, stdlib ``logging.getLogger()`` calls
    produce the same structured output as ``structlog.get_logger()``.

    The ``WEEBOT_LOG_FORMAT`` env var selects the renderer:
    - ``json``  — JSON lines (production)
    - ``console`` — rich console output (default for TTY)
    - ``dev`` — verbose key=value (development)
    """
    format_env = os.environ.get("WEEBOT_LOG_FORMAT", "").lower()
    is_tty = sys.stderr.isatty() if hasattr(sys.stderr, "isatty") else False

    if format_env == "json" or (not is_tty and format_env != "console"):
        renderer = structlog.processors.JSONRenderer()
    elif format_env == "console" or is_tty:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Capture all stdlib logging into the structlog pipeline
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.INFO)
    structlog.stdlib.recreate_defaults(log_level=logging.INFO)


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger for *name*.

    Drop-in replacement for ``logging.getLogger(name)``.
    """
    return structlog.get_logger(name or __name__)
