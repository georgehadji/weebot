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
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionListResponse:
    """List all sessions with optional filtering."""
    sessions = await state_repo.list_sessions(
        user_id=user_id, status=status, limit=limit, offset=offset
    )
    total = await state_repo.count_sessions(user_id=user_id)
    
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
    logger.info("Created session %s", session.id)

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


@router.get("/search")
async def search_sessions(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    limit: int = Query(10, ge=1, le=100),
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> dict:
    """Search sessions with goal→match→resolution bookends."""
    from weebot.application.services.session_search_service import SessionSearchService
    svc = SessionSearchService(state_repo=state_repo)
    results = await svc.search(q, limit=limit)
    return {
        "query": q,
        "count": len(results),
        "results": [r.__dict__ for r in results],
    }

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
    logger.info("Deleted session %s", session_id)

    return {"message": f"Session {session_id} deleted"}


@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    http_request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Cancel a running session."""

    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Cancel via TaskRunner if available, otherwise just mark status.
    # The TaskRunner owns the running asyncio.Task — we must stop it
    # or it will overwrite the FAILED status when it finishes.
    container = http_request.app.state.container
    try:
        from weebot.application.services.task_runner import TaskRunner
        task_runner = container.get(TaskRunner)
        cancelled = await task_runner.cancel_session(session_id)
        if not cancelled:
            # TaskRunner didn't have an active task — mark manually
            session = session.set_status(SessionStatus.FAILED)
            await state_repo.save_session(session)
    except (KeyError, Exception):
        # TaskRunner not registered in container — fall back to status-only
        session = session.set_status(SessionStatus.FAILED)
        await state_repo.save_session(session)
    else:
        # Reload session to get TaskRunner's updated status
        session = await state_repo.load_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    logger.info("Cancelled session %s", session_id)
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

    logger.info("Resumed session %s", session_id)
    return _session_to_response(session)


@router.post("/{session_id}/run", response_model=SessionResponse)
async def run_session(
    session_id: str,
    http_request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Start executing a session's task via the PlanActFlow TaskRunner.

    Called immediately after creating a session to kick off the background
    Plan-Act loop. Returns immediately — the flow runs asynchronously and
    events are streamed via WebSocket /ws/sessions/{session_id}.
    """
    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if session.status not in (SessionStatus.IDLE, SessionStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id} is already {session.status.value}",
        )

    prompt = session.context.get("last_prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="Session has no prompt to execute")

    container = http_request.app.state.container
    try:
        from weebot.application.services.task_runner import TaskRunner
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.event_bus_port import EventBusPort

        task_runner: TaskRunner = container.get(TaskRunner)
        llm = container.get(LLMPort)
        event_bus = container.get(EventBusPort)
        model = session.context.get("model") or None

        from weebot.interfaces.factories import build_tools
        tools = await build_tools(role="admin")
        try:
            factory = task_runner.create_plan_act_factory(
                llm=llm, tools=tools, event_bus=event_bus, model=model
            )
            session = await task_runner.start_session(session, factory)
        except Exception:
            await tools.teardown()
            raise
    except Exception as exc:
        logger.exception("Failed to start session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to start task: {exc}")

    logger.info("Started background task for session %s", session_id)
    return _session_to_response(session)
