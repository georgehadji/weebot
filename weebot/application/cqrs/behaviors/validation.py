"""Validation behavior for CQRS mediator."""
import asyncio
from typing import Any, Callable

from weebot.application.cqrs.base import Command, Query, IPipelineBehavior

class ValidationBehavior(IPipelineBehavior):
    """Pipeline behavior that validates requests before execution."""

    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable[[], Any],
    ) -> Any:
        """Validate and execute request."""
        if hasattr(request, "validate") and callable(request.validate):
            if asyncio.iscoroutinefunction(request.validate):
                await request.validate()
            else:
                request.validate()

        return await next_callable()
