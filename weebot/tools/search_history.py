"""SearchHistoryTool — full-text search over past session events.

Lets the agent search its own history for relevant context, similar
decisions, and past findings.  Reads the FTS5-indexed event table through
``SessionSearchPort`` (H15): ``discover`` finds sessions, ``scroll`` reads the
events around one hit, ``read`` returns one event.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import PrivateAttr

from weebot.application.ports.session_search_port import SessionSearchError, SessionSearchPort
from weebot.domain.models.output_trust import OutputTrust
from weebot.tools.base import BaseTool, ToolResult


class SearchHistoryTool(BaseTool):
    """Search past session events using full-text search."""

    output_trust: ClassVar[OutputTrust] = OutputTrust.EXTERNAL

    name: str = "search_history"
    description: str = (
        "Search past sessions to recall decisions, findings, or similar tasks. "
        "mode=discover (default) returns the sessions that match, best first, each with its "
        "best event. mode=scroll returns the events around one hit (needs session_id and "
        "event_id from a discover result). mode=read returns one event by event_id. "
        "Plain words also match parts of words ('onfig' finds 'config') and non-Latin text. "
        'With syntax=fts the query is FTS5: AND, OR, NOT, "a phrase", prefix*, '
        "event_type:message."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (mode=discover)."},
            "mode": {
                "type": "string",
                "enum": ["discover", "scroll", "read"],
                "description": "discover (default), scroll or read.",
            },
            "syntax": {
                "type": "string",
                "enum": ["text", "fts"],
                "description": "text (default) quotes operators; fts passes FTS5 syntax.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum sessions to return (default: 10).",
                "default": 10,
            },
            "session_id": {"type": "string", "description": "Session of the hit (mode=scroll)."},
            "event_id": {
                "type": "string",
                "description": "Event to scroll around or read (mode=scroll, read).",
            },
            "window": {
                "type": "integer",
                "description": "Events before and after the hit (mode=scroll, default 5).",
                "default": 5,
            },
        },
        "required": [],
    }

    _search: SessionSearchPort = PrivateAttr()

    def __init__(self, search: SessionSearchPort, **data: Any) -> None:
        super().__init__(**data)
        self._search = search

    async def execute(
        self,
        query: str = "",
        mode: str = "discover",
        syntax: str = "text",
        limit: int = 10,
        session_id: str = "",
        event_id: str = "",
        window: int = 5,
        **_: Any,
    ) -> ToolResult:
        try:
            if mode == "scroll":
                return await self._scroll(session_id, event_id, window)
            if mode == "read":
                return await self._read(event_id)
            if mode != "discover":
                return ToolResult.error_result(error=f"Unknown mode: {mode}", output="")
            if not query.strip():
                return ToolResult.error_result(error="query is required for discover", output="")
            return await self._discover(query, syntax, limit)
        except SessionSearchError as exc:
            return ToolResult.error_result(error=str(exc), output="")
        except Exception as exc:
            return ToolResult.error_result(error=f"Search failed: {exc}", output="")

    async def _discover(self, query: str, syntax: str, limit: int) -> ToolResult:
        results = await self._search.discover(
            query, limit=max(1, min(limit, 50)), syntax="fts" if syntax == "fts" else "text"
        )
        if not results:
            return ToolResult.success_result(
                output=f"No results found for: {query}",
                data={"query": query, "results": [], "count": 0},
            )
        lines = [f"## Search Results: {query}", ""]
        for r in results:
            lines.append(f"**Session:** `{r['session_id']}`  **Event:** `{r['event_id']}`")
            lines.append(
                f"**Type:** {r['event_type']}  **Score:** {r['score']:.3f}  "
                f"**Matches:** {r['hits']}  **At:** {r['ts']}"
            )
            lines.append(f"**Summary:** {r['summary'][:200]}")
            if r["content"]:
                lines.append(f"**Detail:** {r['content'][:200]}")
            lines.append("")
        return ToolResult.success_result(
            output="\n".join(lines),
            data={"query": query, "results": results, "count": len(results)},
        )

    async def _scroll(self, session_id: str, event_id: str, window: int) -> ToolResult:
        if not session_id or not event_id:
            return ToolResult.error_result(error="scroll needs session_id and event_id", output="")
        events = await self._search.scroll(session_id, event_id, window=window)
        if not events:
            return ToolResult.error_result(error=f"Event not found: {event_id}", output="")
        lines = [f"## Session {session_id} around {event_id}", ""]
        for e in events:
            marker = ">>" if e["target"] else "  "
            lines.append(f"{marker} [{e['ts']}] {e['event_type']}: {e['summary'][:200]}")
            if e["content"]:
                lines.append(f"     {e['content'][:200]}")
        return ToolResult.success_result(
            output="\n".join(lines), data={"events": events, "count": len(events)}
        )

    async def _read(self, event_id: str) -> ToolResult:
        if not event_id:
            return ToolResult.error_result(error="read needs event_id", output="")
        event = await self._search.read(event_id)
        if event is None:
            return ToolResult.error_result(error=f"Event not found: {event_id}", output="")
        text = f"[{event['ts']}] {event['event_type']}: {event['summary']}\n{event['content']}"
        return ToolResult.success_result(output=text.strip(), data={"event": event})
