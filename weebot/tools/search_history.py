"""SearchHistoryTool — full-text search over past session events.

Lets the agent search its own history for relevant context, similar
decisions, and past findings.  Uses the FTS5-indexed event table.
"""
from __future__ import annotations

from typing import Any

from weebot.tools.base import BaseTool, ToolResult


from pydantic import PrivateAttr


class SearchHistoryTool(BaseTool):
    """Search past session events using full-text search."""

    name: str = "search_history"
    description: str = (
        "Search across all past session events using full-text search. "
        "Use this to recall past decisions, findings, or similar tasks "
        "from previous sessions. Results include session ID, event type, "
        "and a relevance score."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (plain text or FTS5 syntax).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default: 10).",
                "default": 10,
            },
        },
        "required": ["query"],
    }

    _pool: Any = PrivateAttr(default=None)

    def __init__(self, pool=None, **data: Any) -> None:
        super().__init__(**data)
        self._pool = pool

    async def execute(self, query: str, limit: int = 10, **_: Any) -> ToolResult:
        from weebot.infrastructure.persistence.fts5_search import search_events

        if self._pool is None:
            from weebot.infrastructure.persistence.connection_pool import (
                get_or_create_pool,
            )
            self._pool = await get_or_create_pool(
                "./weebot_sessions.db",
                max_read_connections=3,
                enable_wal=True,
            )

        try:
            results = await search_events(self._pool, query, limit=min(limit, 50))
        except Exception as exc:
            return ToolResult.error_result(
                error=f"Search failed: {exc}",
                output="",
            )

        if not results:
            return ToolResult.success_result(
                output=f"No results found for: {query}",
                data={"query": query, "results": [], "count": 0},
            )

        lines = [f"## Search Results: {query}", ""]
        for r in results:
            lines.append(f"**Session:** `{r['session_id'][:16]}...`")
            lines.append(f"**Type:** {r['event_type']}  **Score:** {r['score']:.3f}")
            lines.append(f"**Summary:** {r['summary'][:200]}")
            if r['content']:
                lines.append(f"**Detail:** {r['content'][:200]}")
            lines.append("")

        return ToolResult.success_result(
            output="\n".join(lines),
            data={"query": query, "results": results, "count": len(results)},
        )
