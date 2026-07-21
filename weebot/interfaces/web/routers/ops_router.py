"""Operations Console API — active sessions, plan visualization, cost summary.

Provides the three endpoints from Enhancement 4:
- GET /api/sessions/active
- GET /api/sessions/{session_id}/plan-viz
- GET /api/costs/summary
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from weebot.interfaces.web.auth import get_current_user_id, verify_session_ownership

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/sessions/active")
async def list_active_sessions(
    http_request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """List currently running sessions owned by the current user."""
    current_user = get_current_user_id(http_request)
    try:
        from weebot.application.cqrs.queries import GetActiveSessionsQuery
        from weebot.application.cqrs.mediator import Mediator
        from weebot.application.di import Container

        c = Container()
        c.configure_defaults()
        mediator = c.get(Mediator)
        result = await mediator.send(GetActiveSessionsQuery(user_id=current_user, limit=limit))
        if result.success:
            return {"ok": True, "data": result.data}
        raise HTTPException(status_code=500, detail=result.error or "Unknown error")
    except Exception:
        logger.exception("Failed to list active sessions")
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/sessions/{session_id}/plan-viz")
async def get_plan_visualization(session_id: str, http_request: Request) -> dict:
    """Return DAG node/edge data for a session's current plan."""
    try:
        from weebot.application.cqrs.queries import GetPlanVisualizationQuery
        from weebot.application.cqrs.mediator import Mediator
        from weebot.application.di import Container
        from weebot.application.ports.state_repo_port import StateRepositoryPort

        c = Container()
        c.configure_defaults()

        # Verify ownership before returning plan data
        state_repo = c.get(StateRepositoryPort)
        session = await state_repo.load_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        await verify_session_ownership(http_request, session.user_id)

        mediator = c.get(Mediator)
        result = await mediator.send(GetPlanVisualizationQuery(session_id=session_id))
        if result.success:
            return {"ok": True, "data": result.data}
        if result.resource_not_found:
            raise HTTPException(status_code=404, detail="Session not found")
        raise HTTPException(status_code=500, detail=result.error or "Unknown error")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get plan visualization for session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error") from None


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
    except Exception:
        logger.exception("Failed to get cost summary")
        raise HTTPException(status_code=500, detail="Internal server error") from None
