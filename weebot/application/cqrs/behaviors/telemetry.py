"""Telemetry behavior for CQRS mediator."""

import time
import logging
from typing import Any
from collections.abc import Callable

from weebot.application.cqrs.base import (
    Command,
    Query,
    IPipelineBehavior,
)

logger = logging.getLogger("weebot.telemetry")


class TelemetryBehavior(IPipelineBehavior):
    """Pipeline behavior that logs each request's execution time."""

    async def handle(self, request: Command | Query, next_callable: Callable[[], Any]) -> Any:
        """Track telemetry for the request."""
        start_time = time.perf_counter()
        request_name = type(request).__name__

        try:
            result = await next_callable()
            duration = (time.perf_counter() - start_time) * 1000

            # Duration only: no handler returns its model or token use, so the
            # "Model: unknown, Tokens: 0" this used to print was never right.
            # Model and cost per call are the LLMCallCompleted events (W4.1).
            logger.info(f"CQRS Telemetry: {request_name} took {duration:.2f}ms")
            return result

        except Exception:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"CQRS Telemetry: {request_name} failed after {duration:.2f}ms")
            raise
