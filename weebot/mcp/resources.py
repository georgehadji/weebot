"""Resource data builders for the weebot MCP server.

These are pure functions that build JSON payloads for each resource URI.
They are intentionally separated from server.py so they can be unit-tested
without instantiating a FastMCP server.

Live data is opt-in: pass a StateManager or SchedulingManager instance to
get real runtime snapshots; omit them to get stub payloads.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from weebot.core.activity_stream import ActivityStream

_log = logging.getLogger(__name__)
_INTERNAL_ERROR = "internal_error"

if TYPE_CHECKING:
    # Import only for type hints — avoids circular imports at runtime.
    from weebot.application.skills.skill_registry import SkillRegistry
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
        _log.exception("Failed to build state resource payload: %s", exc)
        return json.dumps(
            {"status": "error", "error": _INTERNAL_ERROR},
            indent=2,
        )


def build_roadmap_json(product_db_path: Optional[str] = None) -> str:
    """Return all requirements grouped by category as a JSON string.

    Args:
        product_db_path: Path to the SQLite database that holds the
                         ``requirements`` table.  When omitted a static
                         stub is returned.
    """
    if product_db_path is None:
        return json.dumps(
            {
                "requirements": [],
                "note": "Pass product_db_path= to WeebotMCPServer for live data.",
            },
            indent=2,
        )

    try:
        import sqlite3
        import datetime as _dt

        with sqlite3.connect(product_db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT req_id, project_id, title, category, priority, status, tags
                   FROM requirements
                   ORDER BY project_id, priority ASC"""
            )
            rows = [dict(r) for r in cursor.fetchall()]

        # Group by project_id then category
        projects: dict[str, Any] = {}
        for req in rows:
            pid = req["project_id"]
            cat = req["category"]
            projects.setdefault(pid, {}).setdefault(cat, []).append(req)

        return json.dumps(
            {
                "total": len(rows),
                "projects": projects,
                "generated_at": _dt.datetime.now().isoformat(),
            },
            indent=2,
        )
    except Exception as exc:
        _log.exception("Failed to build roadmap resource payload: %s", exc)
        return json.dumps({"requirements": [], "error": _INTERNAL_ERROR}, indent=2)


async def build_tools_json(
    tool_discovery: Optional[Any] = None,
    role: Optional[str] = None,
) -> str:
    """Return the tool catalog as a JSON string.

    Args:
        tool_discovery: Optional :class:`~weebot.application.ports.tool_discovery_port.ToolDiscoveryPort`
                        instance.  When provided, live tool manifests are returned;
                        when omitted a static stub is returned.
        role: Optional role filter (e.g. ``"researcher"``, ``"admin"``).
    """
    if tool_discovery is None:
        return json.dumps(
            {
                "tools": [],
                "note": "Pass tool_discovery= to WeebotMCPServer for live tool catalog.",
            },
            indent=2,
        )

    try:
        manifests = await tool_discovery.list_tools(role=role)
        tools = [
            {
                "name": m.name,
                "description": m.description,
                "roles": m.roles,
                "requires_deps": m.requires_deps,
                "mcp_safe": m.mcp_safe,
                "mcp_requires_confirm": m.mcp_requires_confirm,
                "is_experimental": m.is_experimental,
            }
            for m in manifests
        ]
        return json.dumps(
            {
                "tools": tools,
                "total": len(tools),
                "role_filter": role,
            },
            indent=2,
        )
    except Exception as exc:
        _log.exception("Failed to build tools resource payload: %s", exc)
        return json.dumps({"tools": [], "error": _INTERNAL_ERROR}, indent=2)


def build_costs_json(cascade_tracker: Optional[Any] = None) -> str:
    """Return current-session cost and cascade statistics as a JSON string.

    Args:
        cascade_tracker: Optional :class:`~weebot.core.model_cascade_tracker.ModelCascadeTracker`
                         instance.  When provided, live cascade data is returned;
                         when omitted a static stub is returned.
    """
    if cascade_tracker is None:
        return json.dumps(
            {
                "total_decisions": 0,
                "per_tier": {},
                "total_cost_estimate": 0.0,
                "avg_latency_ms": 0.0,
                "cascade_hit_rate": 1.0,
                "recent_decisions": [],
                "note": "Pass cascade_tracker= to WeebotMCPServer for live cost data.",
            },
            indent=2,
        )

    try:
        summary = cascade_tracker.summary()
        recent = cascade_tracker.recent(20)
        summary["recent_decisions"] = [
            {
                "model_name": d.model_name,
                "tier": d.tier.value,
                "outcome": d.outcome.value,
                "latency_ms": d.latency_ms,
                "token_count": d.token_count,
                "cost_estimate": d.cost_estimate,
                "error_message": d.error_message,
                "timestamp": d.timestamp.isoformat(),
            }
            for d in recent
        ]
        return json.dumps(summary, indent=2)
    except Exception as exc:
        _log.exception("Failed to build costs resource payload: %s", exc)
        return json.dumps(
            {"error": _INTERNAL_ERROR, "total_decisions": 0},
            indent=2,
        )


def build_skills_json(skill_registry: Optional[Any] = None) -> str:
    """Return installed skills as a JSON string.

    Args:
        skill_registry: Optional :class:`~weebot.application.skills.skill_registry.SkillRegistry`
                        instance.  When provided, live skill data is returned;
                        when omitted a static stub is returned.
    """
    if skill_registry is None:
        return json.dumps(
            {
                "skills": [],
                "total": 0,
                "note": "Pass skill_registry= to WeebotMCPServer for live skill data.",
            },
            indent=2,
        )

    try:
        skills = skill_registry.list_skills()
        data = [
            {
                "name": s.name,
                "description": getattr(s, "description", ""),
                "version": str(getattr(s, "current_version", "unknown")),
                "triggers": getattr(s, "triggers", []),
                "category": getattr(s, "category", ""),
            }
            for s in skills
        ]
        return json.dumps({"skills": data, "total": len(data)}, indent=2)
    except Exception as exc:
        _log.exception("Failed to build skills resource payload: %s", exc)
        return json.dumps({"skills": [], "error": _INTERNAL_ERROR}, indent=2)


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
        _log.exception("Failed to build schedule resource payload: %s", exc)
        return json.dumps(
            {"jobs": [], "error": _INTERNAL_ERROR},
            indent=2,
        )
