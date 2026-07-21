"""Session API routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.interfaces.web.auth import get_current_user_id, verify_session_ownership
from weebot.interfaces.web.schemas import (
    CreateSessionRequest,
    ResumeSessionRequest,
    SessionResponse,
    SessionListResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


async def get_state_repo(request: Request) -> StateRepositoryPort:
    """Resolve StateRepositoryPort from the application DI container."""
    container = request.app.state.container
    return container.get(StateRepositoryPort)


def _build_deletion_orchestrator(
    request: Request,
    state_repo: StateRepositoryPort,
) -> Any:
    """Build a SessionDeletionOrchestrator with all available stores."""
    from weebot.application.services.session_deletion_orchestrator import (
        SessionDeletionOrchestrator,
    )

    orch = SessionDeletionOrchestrator(state_repo=state_repo)

    # Register known extra stores if available in the container
    container = request.app.state.container

    # Event store
    try:
        from weebot.application.ports.event_bus_port import EventStorePort
        event_store = container.get(EventStorePort)
        if hasattr(event_store, "delete_session"):
            orch.add_store("event_store", event_store, "delete_session")
    except (KeyError, Exception):
        pass

    # Checkpoint store
    try:
        from weebot.infrastructure.persistence.checkpoint_store import (
            SQLiteCheckpointStore,
        )
        checkpoint_store = container.get(SQLiteCheckpointStore)
        if hasattr(checkpoint_store, "delete"):
            orch.add_store("checkpoint_store", checkpoint_store, "delete")
    except (KeyError, Exception):
        pass

    # Gateway session store
    try:
        from weebot.infrastructure.persistence.gateway_session_store import (
            SQLiteGatewaySessionStore,
        )
        gateway_store = container.get(SQLiteGatewaySessionStore)
        orch.add_store("gateway_session_store", gateway_store, "delete_by_session_id")
    except (KeyError, Exception):
        pass

    # Knowledge graph
    try:
        import importlib as _kg_il
        _kg_mod = _kg_il.import_module(
            "weebot.infrastructure.persistence.sqlite_knowledge_graph"
        )
        _kg_cls = getattr(_kg_mod, "SQLiteKnowledgeGraph", None)
        if _kg_cls is not None:
            kg = container.get(_kg_cls)
            if hasattr(kg, "delete_by_session_id"):
                orch.add_store("knowledge_graph", kg, "delete_by_session_id")
    except (KeyError, Exception):
        pass

    return orch


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
    http_request: Request,
    status: str | None = Query(default=None, description="Filter by status"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionListResponse:
    """List all sessions for the current user."""
    effective_user = get_current_user_id(http_request)
    sessions = await state_repo.list_sessions(
        user_id=effective_user, status=status, limit=limit, offset=offset
    )
    total = await state_repo.count_sessions(user_id=effective_user)

    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=total,
    )


@router.post("", response_model=SessionResponse)
async def create_session(
    http_request: Request,
    body: CreateSessionRequest,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Create a new session."""

    import uuid
    context: dict[str, Any] = {"last_prompt": body.prompt, "model": body.model}
    if body.ponytail_mode is not None:
        context["ponytail_mode"] = body.ponytail_mode

    # Override user_id with the authenticated identity
    current_user = get_current_user_id(http_request)

    session = Session(
        id=body.session_id or str(uuid.uuid4()),
        user_id=current_user,
        agent_id=body.agent_id,
        context=context,
    )

    await state_repo.save_session(session)
    logger.info("Created session %s", session.id)

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

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    http_request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Get a specific session by ID."""

    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await verify_session_ownership(http_request, session.user_id)

    return _session_to_response(session)


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    http_request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> dict:
    """Delete a session and all associated data across stores."""

    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await verify_session_ownership(http_request, session.user_id)

    # Use orchestrator to cascade delete across all stores
    orch = _build_deletion_orchestrator(http_request, state_repo)
    results = await orch.delete_session(session_id)

    logger.info("Deleted session %s (results: %s)", session_id, results)

    return {"message": f"Session {session_id} deleted", "results": results}


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

    await verify_session_ownership(http_request, session.user_id)

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
    http_request: Request,
    request: ResumeSessionRequest,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> SessionResponse:
    """Resume a waiting session with user answer."""

    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await verify_session_ownership(http_request, session.user_id)

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

    await verify_session_ownership(http_request, session.user_id)

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
        ponytail_mode = session.context.get("ponytail_mode") or None

        from weebot.interfaces.factories import build_tools
        tools = await build_tools(role="admin")
        try:
            factory = task_runner.create_plan_act_factory(
                llm=llm,
                tools=tools,
                event_bus=event_bus,
                model=model,
                ponytail_mode=ponytail_mode,
            )
            session = await task_runner.start_session(session, factory)
        except Exception:
            await tools.teardown()
            raise
    except Exception:
        logger.exception("Failed to start session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to start task") from None

    logger.info("Started background task for session %s", session_id)
    return _session_to_response(session)
