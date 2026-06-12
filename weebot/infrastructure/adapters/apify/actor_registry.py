"""Apify actor registry — discovers and indexes actors from the store.

Two modes:
  1. File mode  — reads a pre-built apify_actors.json (from fetch_apify_actors.js)
  2. API mode   — queries the live Apify store via ApifyService.search_store

Usage:
    # from file
    registry = ApifyActorRegistry.from_file("/path/to/apify_actors.json")

    # from live API
    registry = ApifyActorRegistry(apify_service)
    await registry.preload(query="scraper")

    actors = registry.search("youtube transcript")
    tool   = registry.create_tool("supreme_coder/youtube-transcript-scraper", service)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.infrastructure.adapters.apify.apify_service import ApifyService
    from weebot.tools.apify_actor_tool import ApifyActorTool

logger = logging.getLogger(__name__)


class ApifyActorRegistry:
    """In-memory catalog of Apify actors with search and tool-factory helpers."""

    def __init__(self, apify_service: Optional["ApifyService"] = None) -> None:
        self._service = apify_service
        self._actors: List[Dict[str, Any]] = []

    # ── construction ───────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path) -> "ApifyActorRegistry":
        """Build registry from a local apify_actors.json file."""
        registry = cls()
        actors = json.loads(Path(path).read_text(encoding="utf-8"))
        # Accept both a plain list and {"actors": [...]} envelope
        if isinstance(actors, dict):
            actors = actors.get("actors", actors.get("items", []))
        registry._actors = actors
        logger.info("ApifyActorRegistry loaded %d actors from file", len(registry._actors))
        return registry

    # ── loading from API ───────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear the in-memory actor catalog."""
        self._actors = []

    async def preload(self, query: str = "", limit: int = 100) -> None:
        """Fetch actors from the live Apify store and append to the cache.

        Duplicate entries (matched by actor ID) are skipped, so calling
        preload() multiple times is safe.
        """
        if self._service is None:
            raise RuntimeError("ApifyActorRegistry requires an ApifyService for preload()")
        known_ids: set[str] = {
            a.get("id") or f"{a.get('username','')}/{a.get('name','')}"
            for a in self._actors
        }
        resp = await self._service.execute("search_store", query=query, limit=limit)
        if not resp.success:
            logger.warning("Failed to preload Apify store: %s", resp.error)
            return
        data = resp.data or {}
        items = data.get("items", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            new_items = [
                a for a in items
                if (a.get("id") or f"{a.get('username','')}/{a.get('name','')}") not in known_ids
            ]
            self._actors.extend(new_items)
            logger.info(
                "ApifyActorRegistry preloaded %d new actors (%d duplicates skipped)",
                len(new_items), len(items) - len(new_items),
            )

    # ── search ─────────────────────────────────────────────────────────────

    def search(
        self, query: str, category: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search cached actors by query string and optional category filter."""
        query_lower = query.lower()
        results = []
        for actor in self._actors:
            name = (actor.get("name") or actor.get("title") or "").lower()
            desc = (actor.get("description") or "").lower()
            cats = [c.lower() for c in (actor.get("categories") or [])]
            if query_lower and query_lower not in name and query_lower not in desc:
                continue
            if category and category.lower() not in cats:
                continue
            results.append(actor)
            if len(results) >= limit:
                break
        return results

    def get(self, actor_id: str) -> Optional[Dict[str, Any]]:
        """Return actor metadata by full ID (username/name)."""
        for actor in self._actors:
            aid = actor.get("id") or f"{actor.get('username','')}/{actor.get('name','')}"
            if aid == actor_id:
                return actor
        return None

    # ── tool factory ───────────────────────────────────────────────────────

    def create_tool(
        self,
        actor_id: str,
        service: "ApifyService",
        run_input_schema: Optional[Dict[str, Any]] = None,
    ) -> "ApifyActorTool":
        """Instantiate an ApifyActorTool for the given actor ID."""
        from weebot.tools.apify_actor_tool import ApifyActorTool

        meta = self.get(actor_id) or {}
        description = meta.get("description") or f"Run Apify actor {actor_id}"
        tool_name = "apify_" + actor_id.replace("/", "_").replace("-", "_").replace("~", "_")
        schema = run_input_schema or {
            "type": "object",
            "properties": {
                "run_input": {
                    "type": "object",
                    "description": "JSON input payload for the actor",
                }
            },
            "required": [],
        }
        return ApifyActorTool(
            name=tool_name,
            description=description,
            parameters=schema,
            actor_id=actor_id,
            apify_service=service,
        )

    def __len__(self) -> int:
        return len(self._actors)
