"""Dashboard metrics API routes."""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter

from weebot.interfaces.web.schemas.responses import DashboardMetricsResponse, CostData, ModelUsage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_db_path() -> str:
    """Get the SQLite database path."""
    from weebot.config.settings import WORKSPACE_ROOT
    return str(WORKSPACE_ROOT / "weebot_sessions.db")


@router.get("/metrics", response_model=DashboardMetricsResponse)
async def get_dashboard_metrics() -> DashboardMetricsResponse:
    """Get dashboard metrics including sessions, costs, and system stats."""
    db_path = get_db_path()
    
    # Default values
    total_sessions = 0
    active_sessions = 0
    completed_sessions = 0
    
    # Get session counts from database
    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Total sessions
            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]
            
            # Active sessions (status = 'running' or 'active')
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('running', 'active')")
            active_sessions = cursor.fetchone()[0]
            
            # Completed sessions
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'completed'")
            completed_sessions = cursor.fetchone()[0]
            
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to query session metrics: {e}")
    
    # Generate sample cost data for last 7 days
    # In a real implementation, this would come from a cost tracking table
    daily_costs: List[CostData] = []
    today = datetime.now()
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        # Generate somewhat realistic sample data based on day of week
        base_cost = 0.5 if date.weekday() < 5 else 0.2  # Weekdays higher
        daily_costs.append(CostData(
            date=date.strftime("%a"),
            cost=round(base_cost + (i % 3) * 0.1, 2),
            tokens=int((base_cost * 20000) + (i % 3) * 1000)
        ))
    
    # Sample model usage - in real implementation would track per-model usage
    model_usage: List[ModelUsage] = [
        ModelUsage(name="GPT-4o", cost=2.45, usage=45),
        ModelUsage(name="Claude Sonnet", cost=1.89, usage=62),
        ModelUsage(name="DeepSeek", cost=0.45, usage=120),
        ModelUsage(name="Gemini Pro", cost=0.12, usage=28),
    ]
    
    # Get system metrics
    try:
        import psutil
        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
    except ImportError:
        cpu_usage = 0.0
        memory_usage = 0.0
    
    # Calculate database size
    db_size = "0 MB"
    try:
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            if size_bytes < 1024 * 1024:
                db_size = f"{size_bytes / 1024:.1f} KB"
            else:
                db_size = f"{size_bytes / (1024 * 1024):.1f} MB"
    except Exception:
        pass
    
    # Estimate requests per minute (sample data)
    requests_per_minute = 12 if active_sessions > 0 else 0
    
    # Calculate average response time (sample)
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
