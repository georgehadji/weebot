"""Telemetry behavior for CQRS mediator."""
import time
import logging
from typing import Any, Callable

from weebot.application.cqrs.base import Command, Query, IPipelineBehavior, CommandResult, QueryResult

logger = logging.getLogger("weebot.telemetry")

class TelemetryBehavior(IPipelineBehavior):
    """Pipeline behavior that tracks execution time and token usage."""

    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable[[], Any],
    ) -> Any:
        """Track telemetry for the request."""
        start_time = time.perf_counter()
        request_name = type(request).__name__

        try:
            result = await next_callable()
            duration = (time.perf_counter() - start_time) * 1000

            # Extract metadata if available
            tokens = 0
            model = "unknown"

            if isinstance(result, (CommandResult, QueryResult)) and result.data:
                if isinstance(result.data, dict):
                    tokens = result.data.get("tokens_used", 0)
                    model = result.data.get("model_used", "unknown")

            logger.info(
                f"CQRS Telemetry: {request_name} took {duration:.2f}ms. "
                f"Model: {model}, Tokens: {tokens}"
            )
            return result

        except Exception:
            duration = (time.perf_counter() - start_time) * 1000
            logger.error(f"CQRS Telemetry: {request_name} failed after {duration:.2f}ms")
            raise
