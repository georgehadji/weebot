"""API routers for web interface."""
from __future__ import annotations

from .sessions import router as sessions_router
from .models import router as models_router
from .health import router as health_router
from .dashboard import router as dashboard_router
from .behavior_router import router as behavior_router

__all__ = ["sessions_router", "models_router", "health_router", "dashboard_router", "behavior_router"]
