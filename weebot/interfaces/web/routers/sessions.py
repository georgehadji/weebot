"""Session API routes."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.interfaces.web.schemas import (
    CreateSessionRequest,
    ResumeSessionRequest,
    SessionResponse,
    SessionListResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


async def get_state_repo(request: Request) -> StateRepositoryPort:
    """Resolve StateRepositoryPort from the application DI container."""
    container = request.app.state.container
    return container.get(StateRepositoryPort)


def _session_to_response(session: Session) -> SessionResponse:
    """Convert Session domain model to API response."""
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        agent_id=session.agent_id,
        status=session.status.value,
        title=session.title,
        context=session.context,
        created_at=session.created_at,
        updated_at=session.updated_at,
        event_count=len(session.events),
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    user_id: Optional[str] = Query(default=None, description="Filter by user ID"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    state_repo: StateRepositoryPort = Depends(get_state_repo),  # TODO: proper DI
) -> SessionListResponse:
    """List all sessions with optional filtering."""
    # TODO: Implement proper dependency injection
    
    sessions = await state_repo.list_sessions(user_id=user_id)
    
    # Filter by status if provided
    if status:
        sessions = [s for s in sessions if s.status.value == status]
    
    total = len(sessions)
    sessions = sessions[offset:offset + limit]
    
    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=total,
    )


@router.post("", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Create a new session."""
    
    import uuid
    session = Session(
        id=request.session_id or str(uuid.uuid4()),
        user_id=request.user_id,
        agent_id=request.agent_id,
        context={"last_prompt": request.prompt, "model": request.model},
    )
    
    await state_repo.save_session(session)
    logger.info(f"Created session {session.id}")
    
    return _session_to_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Get a specific session by ID."""
    
    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    return _session_to_response(session)


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> dict:
    """Delete a session."""
    
    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    await state_repo.delete_session(session_id)
    logger.info(f"Deleted session {session_id}")
    
    return {"message": f"Session {session_id} deleted"}


@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Cancel a running session."""
    
    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    # TODO: Actually cancel the running flow
    session = session.set_status(SessionStatus.FAILED)
    await state_repo.save_session(session)
    
    logger.info(f"Cancelled session {session_id}")
    return _session_to_response(session)


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session(
    session_id: str,
    request: ResumeSessionRequest,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Resume a waiting session with user answer."""
    
    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    if session.status != SessionStatus.WAITING:
        raise HTTPException(
            status_code=400, 
            detail=f"Session {session_id} is not waiting for input (status: {session.status.value})"
        )
    
    # Add user message and update status
    from weebot.domain.models.event import MessageEvent
    session = session.add_event(MessageEvent(role="user", message=request.answer))
    session = session.set_status(SessionStatus.RUNNING)
    await state_repo.save_session(session)
    
    logger.info(f"Resumed session {session_id}")
    return _session_to_response(session)
