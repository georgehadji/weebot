"""
State Coordinator - Unifies multiple state management systems

This module provides a single interface to coordinate between:
- StateManager (persistent state)
- AgentContext (in-memory shared context)
- ActivityStream (event logging)
- ResponseCache (caching)

The coordinator simplifies access to state management functionality
while preserving the specialized behavior of each component.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from weebot.activity_stream import ActivityStream, ActivityEvent
from weebot.ai_router import ResponseCache
from weebot.core.agent_context import AgentContext, EventBroker
from weebot.state_manager import StateManager, ProjectState, ProjectStatus
from weebot.application.ports.state_repo_port import StateRepositoryPort

_log = logging.getLogger(__name__)


class StateCoordinator:
    """
    Coordinates multiple state management systems with a unified interface.
    
    This class provides a single entry point for all state-related operations
    while maintaining the specialized functionality of each underlying system.
    """
    
    def __init__(
        self,
        db_path: str = "projects.db",
        cache_dir: Path = Path("cache"),
        activity_buffer_size: int = 200,
        state_repository: Optional[StateRepositoryPort] = None,
    ):
        # Initialize all state management systems
        self.state_manager = StateManager(db_path=db_path)
        self.state_repository = state_repository
        self.response_cache = ResponseCache(cache_dir=cache_dir)
        self.activity_stream = ActivityStream(max_size=activity_buffer_size)
        
        # Track active contexts
        self._contexts: Dict[str, AgentContext] = {}
    
    # -------------------------------------------------------------------------
    # Project State Management (delegates to StateManager)
    # -------------------------------------------------------------------------
    
    def create_project(self, project_id: str, description: str) -> ProjectState:
        """Create a new project with initial state."""
        return self.state_manager.create_project(project_id, description)
    
    def save_state(self, state: ProjectState) -> None:
        """Save project state to persistent storage."""
        self.state_manager.save_state(state)
    
    async def save_state_async(self, state: ProjectState) -> None:
        """Save project state asynchronously."""
        await self.state_manager.save_state_async(state)
    
    def load_state(self, project_id: str) -> Optional[ProjectState]:
        """Load project state from persistent storage."""
        return self.state_manager.load_state(project_id)
    
    async def load_state_async(self, project_id: str) -> Optional[ProjectState]:
        """Load project state asynchronously."""
        return await self.state_manager.load_state_async(project_id)
    
    def list_projects(self) -> List[Dict]:
        """List all projects."""
        return self.state_manager.list_projects()
    
    # -------------------------------------------------------------------------
    # Context Management (delegates to AgentContext)
    # -------------------------------------------------------------------------
    
    def create_orchestrator_context(self) -> AgentContext:
        """Create a root orchestrator context."""
        context = AgentContext.create_orchestrator(
            activity_stream=self.activity_stream,
            state_manager=self.state_manager,
        )
        self._contexts[context.agent_id] = context
        return context
    
    def create_child_context(
        self,
        parent_context: AgentContext,
        parent_agent_id: str,
        role: str
    ) -> AgentContext:
        """Create a child context inheriting from parent."""
        context = AgentContext.create_child(parent_context, parent_agent_id, role)
        self._contexts[context.agent_id] = context
        return context
    
    def get_context(self, agent_id: str) -> Optional[AgentContext]:
        """Get an active context by agent ID."""
        return self._contexts.get(agent_id)
    
    # -------------------------------------------------------------------------
    # Activity Stream Management (delegates to ActivityStream)
    # -------------------------------------------------------------------------
    
    def log_activity(self, project_id: str, kind: str, message: str) -> None:
        """Log an activity event."""
        self.activity_stream.push(project_id, kind, message)
    
    def get_recent_activities(
        self,
        n: int = 50,
        project_id: Optional[str] = None
    ) -> List[ActivityEvent]:
        """Get recent activity events."""
        return self.activity_stream.recent(n=n, project_id=project_id)
    
    # -------------------------------------------------------------------------
    # Caching (delegates to ResponseCache)
    # -------------------------------------------------------------------------
    
    def get_cached_response(self, key: str) -> Optional[str]:
        """Get a cached response."""
        return self.response_cache.get(key)
    
    def cache_response(self, key: str, value: str) -> None:
        """Cache a response."""
        self.response_cache.set(key, value)
    
    # -------------------------------------------------------------------------
    # Unified Operations
    # -------------------------------------------------------------------------
    
    async def update_project_status(
        self,
        project_id: str,
        status: ProjectStatus,
        activity_message: Optional[str] = None
    ) -> bool:
        """Update project status with optional activity logging."""
        state = await self.load_state_async(project_id)
        if not state:
            _log.error(f"Could not update status for unknown project: {project_id}")
            return False
        
        state.status = status
        await self.save_state_async(state)
        
        if activity_message:
            self.log_activity(project_id, "status", activity_message)
        
        return True
    
    async def store_agent_result(
        self,
        context: AgentContext,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None
    ) -> bool:
        """Store a result in the agent context with optional persistence."""
        success = await context.store_result(key, value, tags)
        
        if success:
            # Optionally also store in persistent state if needed
            if context.state_manager:
                # Update the project state with the new result
                state = await context.state_manager.load_state_async(context.orchestrator_id)
                if state:
                    state.context[key] = value
                    await context.state_manager.save_state_async(state)
        
        return success
    
    def close(self) -> None:
        """Close all managed resources."""
        self.state_manager.close()
        # Clear contexts
        self._contexts.clear()
    
    async def close_async(self) -> None:
        """Close all managed resources asynchronously."""
        await self.state_manager.close_async()
        # Clear contexts
        self._contexts.clear()


# Global coordinator instance (singleton pattern)
_coordinator: Optional[StateCoordinator] = None


def get_state_coordinator() -> StateCoordinator:
    """Get the global state coordinator instance."""
    global _coordinator
    if _coordinator is None:
        _coordinator = StateCoordinator()
    return _coordinator