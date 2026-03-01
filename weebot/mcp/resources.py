"""Resource data builders for the weebot MCP server.

These are pure functions that build JSON payloads for each resource URI.
They are intentionally separated from server.py so they can be unit-tested
without instantiating a FastMCP server.
"""
from __future__ import annotations

import json

from weebot.activity_stream import ActivityStream


def build_activity_json(stream: ActivityStream, n: int = 50) -> str:
    """Return the last *n* activity events as a JSON string (newest-first)."""
    events = stream.recent(n)
    return json.dumps(
        [
            {
                "project_id": e.project_id,
                "kind": e.kind,
                "message": e.message,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ],
        indent=2,
    )


def build_state_json() -> str:
    """Return a minimal agent state snapshot as a JSON string."""
    return json.dumps(
        {
            "status": "idle",
            "version": "1.0.0",
            "note": "Attach StateManager for live agent state.",
        },
        indent=2,
    )


def build_schedule_json() -> str:
    """Return the current schedule list as a JSON string."""
    return json.dumps(
        {
            "jobs": [],
            "note": "Attach SchedulingManager for live schedule data.",
        },
        indent=2,
    )
