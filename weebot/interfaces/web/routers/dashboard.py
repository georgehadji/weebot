"""Dashboard metrics API routes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import SessionStatus
from weebot.interfaces.web.schemas.responses import DashboardMetricsResponse, CostData, ModelUsage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def get_state_repo(request: Request) -> StateRepositoryPort:
    """Resolve StateRepositoryPort from the application DI container."""
    container = request.app.state.container
    return container.get(StateRepositoryPort)


@router.get("/metrics", response_model=DashboardMetricsResponse)
async def get_dashboard_metrics(
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> DashboardMetricsResponse:
    """Get dashboard metrics including sessions, costs, and system stats."""
    # Get session counts from the state repository via the DI container
    total_sessions = 0
    active_sessions = 0
    completed_sessions = 0

    try:
        all_sessions = await state_repo.list_sessions()
        total_sessions = len(all_sessions)
        active_sessions = sum(1 for s in all_sessions if s.status == SessionStatus.RUNNING)
        completed_sessions = sum(1 for s in all_sessions if s.status == SessionStatus.COMPLETED)
    except Exception as e:
        logger.warning(f"Failed to query session metrics: {e}")

    # Generate sample cost data for last 7 days
    # This is placeholder data; a real implementation would use a cost tracking table
    daily_costs: list[CostData] = []
    today = datetime.now()
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        base_cost = 0.5 if date.weekday() < 5 else 0.2  # Weekdays higher
        daily_costs.append(
            CostData(
                date=date.strftime("%a"),
                cost=round(base_cost + (i % 3) * 0.1, 2),
                tokens=int((base_cost * 20000) + (i % 3) * 1000),
            )
        )

    # Sample model usage - placeholder until per-model tracking is implemented
    model_usage: list[ModelUsage] = [
        ModelUsage(name="GPT-4o", cost=2.45, usage=45),
        ModelUsage(name="Claude Sonnet", cost=1.89, usage=62),
        ModelUsage(name="DeepSeek", cost=0.45, usage=120),
        ModelUsage(name="Gemini Pro", cost=0.12, usage=28),
    ]

    # Get system metrics
    cpu_usage = 0.0
    memory_usage = 0.0
    try:
        import psutil  # type: ignore[import-untyped]

        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
    except ImportError:
        pass

    # Database size — read from the session store file if available
    db_size = "0 MB"
    try:
        from weebot.config.settings import WORKSPACE_ROOT

        db_path = WORKSPACE_ROOT / "weebot_sessions.db"
        if db_path.exists():
            size_bytes = db_path.stat().st_size
            if size_bytes < 1024 * 1024:
                db_size = f"{size_bytes / 1024:.1f} KB"
            else:
                db_size = f"{size_bytes / (1024 * 1024):.1f} MB"
    except Exception:
        pass

    requests_per_minute = 12 if active_sessions > 0 else 0
    avg_response_time = 245 if total_sessions > 0 else 0

    return DashboardMetricsResponse(
        total_sessions=total_sessions,
        active_sessions=active_sessions,
        completed_sessions=completed_sessions,
        daily_costs=daily_costs,
        model_usage=model_usage,
        total_cost=sum(d.cost for d in daily_costs),
        total_tokens=sum(d.tokens for d in daily_costs),
        cpu_usage=round(cpu_usage, 1),
        memory_usage=round(memory_usage, 1),
        db_size=db_size,
        requests_per_minute=requests_per_minute,
        avg_response_time=avg_response_time,
    )
