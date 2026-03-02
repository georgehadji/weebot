"""Resource data builders for the weebot MCP server.

These are pure functions that build JSON payloads for each resource URI.
They are intentionally separated from server.py so they can be unit-tested
without instantiating a FastMCP server.

Live data is opt-in: pass a StateManager or SchedulingManager instance to
get real runtime snapshots; omit them to get stub payloads.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from weebot.activity_stream import ActivityStream

if TYPE_CHECKING:
    # Import only for type hints — avoids circular imports at runtime.
    from weebot.state_manager import StateManager
    from weebot.scheduling.scheduler import SchedulingManager


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


def build_state_json(state_manager: Optional[Any] = None) -> str:
    """Return an agent state snapshot as a JSON string.

    Args:
        state_manager: Optional :class:`~weebot.state_manager.StateManager`
                       instance.  When provided, the snapshot reflects live
                       project data; when omitted a static stub is returned.
    """
    if state_manager is None:
        return json.dumps(
            {
                "status": "idle",
                "version": "1.0.0",
                "note": "Pass state_manager= to WeebotMCPServer for live data.",
            },
            indent=2,
        )

    try:
        projects = state_manager.list_projects()
        active = [p for p in projects if p.get("status") not in ("completed", "failed")]
        return json.dumps(
            {
                "status": "active" if active else "idle",
                "version": "1.0.0",
                "total_projects": len(projects),
                "active_projects": len(active),
                "projects": projects[:10],  # cap to avoid huge payloads
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps(
            {"status": "error", "error": str(exc)},
            indent=2,
        )


def build_schedule_json(scheduler: Optional[Any] = None) -> str:
    """Return the current schedule list as a JSON string.

    Args:
        scheduler: Optional :class:`~weebot.scheduling.scheduler.SchedulingManager`
                   instance.  When provided, live scheduled jobs are returned;
                   when omitted a static stub is returned.
    """
    if scheduler is None:
        return json.dumps(
            {
                "jobs": [],
                "note": "Pass scheduler= to WeebotMCPServer for live schedule data.",
            },
            indent=2,
        )

    try:
        jobs = scheduler.list_jobs()
        serialised = []
        for job in jobs:
            entry: dict = {}
            if hasattr(job, "to_dict"):
                entry = job.to_dict()
            else:
                # Duck-type: grab common fields if present.
                for field in ("job_id", "name", "status", "trigger_type", "next_run"):
                    val = getattr(job, field, None)
                    if val is not None:
                        entry[field] = str(val)
            serialised.append(entry)
        return json.dumps({"jobs": serialised, "total": len(serialised)}, indent=2)
    except Exception as exc:
        return json.dumps(
            {"jobs": [], "error": str(exc)},
            indent=2,
        )
