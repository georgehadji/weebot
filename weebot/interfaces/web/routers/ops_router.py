"""Operations Console API — active sessions, plan visualization, cost summary.

Provides the three endpoints from Enhancement 4:
- GET /api/sessions/active
- GET /api/sessions/{session_id}/plan-viz
- GET /api/costs/summary
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/sessions/active")
async def list_active_sessions(
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """List all currently running sessions with flow state and progress.

    Returns each session's ID, status, step count, steps completed,
    tool calls made, and elapsed event count.
    """
    try:
        from weebot.application.cqrs.queries import GetActiveSessionsQuery
        from weebot.application.cqrs.mediator import Mediator
        from weebot.application.di import Container

        c = Container()
        c.configure_defaults()
        mediator = c.get(Mediator)
        result = await mediator.send(GetActiveSessionsQuery(limit=limit))
        if result.success:
            return {"ok": True, "data": result.data}
        raise HTTPException(status_code=500, detail=result.error or "Unknown error")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sessions/{session_id}/plan-viz")
async def get_plan_visualization(session_id: str) -> dict:
    """Return DAG node/edge data for a session's current plan.

    Returns plan status, nodes (steps with status/result), and edges
    (sequential dependencies between steps).
    """
    try:
        from weebot.application.cqrs.queries import GetPlanVisualizationQuery
        from weebot.application.cqrs.mediator import Mediator
        from weebot.application.di import Container

        c = Container()
        c.configure_defaults()
        mediator = c.get(Mediator)
        result = await mediator.send(GetPlanVisualizationQuery(session_id=session_id))
        if result.success:
            return {"ok": True, "data": result.data}
        if result.resource_not_found:
            raise HTTPException(status_code=404, detail="Session not found")
        raise HTTPException(status_code=500, detail=result.error or "Unknown error")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/costs/summary")
async def get_cost_summary(
    window_hours: int = Query(default=24, ge=1, le=720),
) -> dict:
    """Return cost and model cascade statistics for the given time window.

    Returns total decisions, per-tier success/failure/circuit_open counts,
    total cost estimate, average latency, and cascade hit rate.
    """
    try:
        from weebot.application.cqrs.queries import GetCostSummaryQuery
        from weebot.application.cqrs.mediator import Mediator
        from weebot.application.di import Container

        c = Container()
        c.configure_defaults()
        mediator = c.get(Mediator)
        result = await mediator.send(GetCostSummaryQuery(window_hours=window_hours))
        if result.success:
            return {"ok": True, "data": result.data}
        raise HTTPException(status_code=500, detail=result.error or "Unknown error")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
