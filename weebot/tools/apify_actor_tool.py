"""ApifyActorTool — runs any Apify actor as a weebot BaseTool.

Each instance is bound to a specific actor_id and an ApifyService.
The 'run_input' parameter is passed directly to the actor as its JSON input.

Example:
    service = ApifyService()
    await service.initialize()
    tool = ApifyActorTool(
        name="apify_google_search",
        description="Google SERP scraper",
        parameters={...},
        actor_id="apify/google-search-scraper",
        apify_service=service,
    )
    result = await tool.execute(run_input={"queries": ["weebot AI"], "maxPagesPerQuery": 1})
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ApifyActorTool(BaseTool):
    """Generic Apify actor runner bound to a single actor_id."""

    actor_id: str
    apify_service: Any  # ApifyService — Any to avoid circular import

    # Network-heavy; allow generous default timeout.
    default_timeout_seconds: int = 150

    async def execute(
        self,
        run_input: Optional[Dict[str, Any]] = None,
        memory_mbytes: int = 256,
        **kwargs: Any,
    ) -> ToolResult:
        """Run the actor synchronously and return its dataset items.

        Args:
            run_input: JSON input payload forwarded to the Apify actor.
            memory_mbytes: Apify container memory allocation (default 256 MB).
        """
        payload = run_input if run_input is not None else (kwargs or {})
        try:
            resp = await self.apify_service.execute(
                "run_actor_sync",
                actor_id=self.actor_id,
                run_input=payload,
                memory_mbytes=memory_mbytes,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.error_result(
                f"Apify actor '{self.actor_id}' raised an exception: {exc}"
            )

        if not resp.success:
            return ToolResult.error_result(
                f"Apify actor '{self.actor_id}' failed: {resp.error}",
                output=f"status_code={resp.status_code}",
            )

        raw = resp.data
        # Apify sync endpoint returns the items list directly or wrapped
        items: list = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("items", [raw])

        preview = json.dumps(items[:50], indent=2, ensure_ascii=False)
        return ToolResult.success_result(
            output=preview,
            data={
                "items": items,
                "count": len(items),
                "actor_id": self.actor_id,
            },
            execution_time_ms=resp.execution_time_ms,
        )

    async def health_check(self) -> bool:
        from weebot.infrastructure.external_service_integration import ServiceStatus

        status = await self.apify_service.health_check()
        return status == ServiceStatus.HEALTHY
