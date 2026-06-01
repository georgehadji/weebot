"""Logging behavior for CQRS mediator."""
from __future__ import annotations

import logging
from typing import Any, Callable

from weebot.application.cqrs.base import Command, IPipelineBehavior, Query


class LoggingBehavior(IPipelineBehavior):
    """Pipeline behavior that logs command/query execution.

    Example:
        mediator = Mediator()
        mediator.add_pipeline_behavior(LoggingBehavior())
    """

    def __init__(self, logger_name: str = "weebot.cqrs"):
        """Initialize the logging behavior.

        Args:
            logger_name: Name for the logger.
        """
        self._logger = logging.getLogger(logger_name)

    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable,
    ) -> Any:
        """Log request execution."""
        request_name = type(request).__name__
        self._logger.debug(f"Executing {request_name}")

        try:
            result = await next_callable()
            self._logger.debug(f"Completed {request_name}")
            return result
        except Exception as e:
            self._logger.error(f"Failed {request_name}: {e}")
            raise
