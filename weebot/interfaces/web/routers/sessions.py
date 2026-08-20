"""Session API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.interfaces.web.auth import (
    get_current_user_id,
    require_mutation_identity,
    verify_session_ownership,
)
from weebot.interfaces.web.dependencies import build_deletion_orchestrator
from weebot.interfaces.web.schemas import (
    CreateSessionRequest,
    ResumeSessionRequest,
    SessionInputRequest,
    SessionResponse,
    SessionListResponse,
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

    return SessionListResponse(sessions=[_session_to_response(s) for s in sessions], total=total)


@router.post("", response_model=SessionResponse)
async def create_session(
    http_request: Request,
    body: CreateSessionRequest,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    _mutation: None = Depends(require_mutation_identity),
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
    return {"query": q, "count": len(results), "results": [r.__dict__ for r in results]}


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
    _mutation: None = Depends(require_mutation_identity),
) -> dict:
    """Delete a session and all associated data across stores."""

    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await verify_session_ownership(http_request, session.user_id)

    # Use orchestrator to cascade delete across all stores
    orch = build_deletion_orchestrator(http_request, state_repo)
    results = await orch.delete_session(session_id)

    logger.info("Deleted session %s (results: %s)", session_id, results)

    return {"message": f"Session {session_id} deleted", "results": results}


@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    http_request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    _mutation: None = Depends(require_mutation_identity),
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
        from weebot.application.ports.task_runner_port import TaskRunnerPort

        task_runner = container.get(TaskRunnerPort)
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
    _mutation: None = Depends(require_mutation_identity),
) -> SessionResponse:
    """Resume a waiting session with user answer."""

    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await verify_session_ownership(http_request, session.user_id)

    if session.status != SessionStatus.WAITING:
        raise HTTPException(
            status_code=400,
            detail=f"Session {session_id} is not waiting for input (status: {session.status.value})",
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
    _mutation: None = Depends(require_mutation_identity),
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

    if session.status not in (SessionStatus.PENDING, SessionStatus.FAILED):
        raise HTTPException(
            status_code=409, detail=f"Session {session_id} is already {session.status.value}"
        )

    prompt = session.context.get("last_prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="Session has no prompt to execute")

    container = http_request.app.state.container
    try:
        from weebot.application.ports.task_runner_port import TaskRunnerPort
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.ports.event_bus_port import EventBusPort
        from weebot.application.ports.steering_port import SteeringPort

        task_runner: TaskRunnerPort = container.get(TaskRunnerPort)
        llm = container.get(LLMPort)
        event_bus = container.get(EventBusPort)
        steering = container.get(SteeringPort)
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
                steering=steering,
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


@router.post("/{session_id}/steer")
async def steer_session(
    session_id: str,
    http_request: Request,
    request: ResumeSessionRequest,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    _mutation: None = Depends(require_mutation_identity),
) -> dict:
    """Inject non-blocking mid-execution feedback into a running session.

    Unlike ``/resume`` (which only applies while the flow is WAITING for
    an explicit question), steering is delivered while the flow is
    RUNNING and observed at the next step boundary — see
    ``SteeringPort.poll()`` in ``PlanActFlow``. Reuses ``ResumeSessionRequest``'s
    ``{"answer": str}`` shape since the payload is the same: free text.
    """
    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await verify_session_ownership(http_request, session.user_id)

    if session.status != SessionStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail=f"Session {session_id} is not running (status: {session.status.value}); "
            "steering only applies to an in-flight session — use /resume or /input instead",
        )

    from weebot.application.ports.steering_port import SteeringPort

    container = http_request.app.state.container
    steering = container.get(SteeringPort)
    await steering.send(session_id, request.answer)

    logger.info("Steered session %s", session_id)
    return {"message": f"Steering message delivered to session {session_id}"}


@router.post("/{session_id}/input")
async def send_session_input(
    session_id: str,
    http_request: Request,
    request: SessionInputRequest,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    _mutation: None = Depends(require_mutation_identity),
) -> dict:
    """Single entry point for the composer — start / resume / steer / chat.

    Resolves which verb applies from the session's current status (see
    ``application/use_cases/dispatch_session_input.py``) so the frontend
    never has to branch on session state before deciding which of four
    endpoints to call.
    """
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.steering_port import SteeringPort
    from weebot.application.ports.task_runner_port import TaskRunnerPort
    from weebot.application.use_cases.dispatch_session_input import (
        SessionInputContext,
        dispatch_session_input,
    )
    from weebot.interfaces.factories import build_tools

    session = await state_repo.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await verify_session_ownership(http_request, session.user_id)

    container = http_request.app.state.container
    ctx = SessionInputContext(
        session=session,
        text=request.text,
        client_msg_id=request.client_msg_id,
        model=request.model,
        state_repo=state_repo,
        task_runner=container.get(TaskRunnerPort),
        llm=container.get(LLMPort),
        event_bus=container.get(EventBusPort),
        steering=container.get(SteeringPort),
        build_tools=lambda: build_tools(role="admin"),
        build_chat_flow=container.build_chat_flow,
    )

    try:
        result = await dispatch_session_input(ctx)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception:
        logger.exception("Failed to dispatch input for session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to process input") from None

    logger.info("Dispatched %s input for session %s", result.verb, session_id)
    return {"verb": result.verb, "session": _session_to_response(result.session)}
