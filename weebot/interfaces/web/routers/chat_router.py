"""Chat REST API router — conversational chat endpoints.

Provides:
  POST /api/chat        — send a message, block until the full LLM response
  POST /api/chat/stream — send a message, stream the response as SSE
  GET /api/chat/history — list chat sessions
  GET /api/chat/{id}    — retrieve session details
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session
from weebot.interfaces.web.auth import (
    get_current_user_id,
    require_mutation_identity,
    verify_session_ownership,
)
from weebot.interfaces.web.schemas.chat_schemas import (
    ChatRequest,
    ChatResponse,
    ChatSessionList,
    ChatSessionSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


async def get_container(request: Request) -> Container:
    """Resolve the DI container from app state."""
    return request.app.state.container


async def get_state_repo(request: Request) -> StateRepositoryPort:
    container = request.app.state.container
    return container.get(StateRepositoryPort)


async def _resolve_session(
    body: ChatRequest, request: Request, state_repo: StateRepositoryPort
) -> Session:
    """Load the session named in ``body.session_id``, or start a new one.

    Shared by both the blocking and streaming endpoints so ownership
    verification and session creation cannot drift between the two.
    """
    current_user = get_current_user_id(request)
    if body.session_id:
        session = await state_repo.load_session(body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        await verify_session_ownership(request, session.user_id)
        return session

    session = Session(
        id=f"chat-{uuid.uuid4().hex[:8]}", user_id=current_user, agent_id="chat-agent"
    )
    await state_repo.save_session(session)
    return session


@router.post("", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    _mutation: None = Depends(require_mutation_identity),
) -> ChatResponse:
    """Send a chat message and receive the LLM response."""
    container = request.app.state.container
    session = await _resolve_session(body, request, state_repo)

    # Build and run the chat flow
    flow = container.build_chat_flow(session=session, model=body.model or None)
    # Run the flow and collect events
    events: list = []
    async for event in flow.run(body.message):
        events.append(event)

    # Extract the last assistant message
    response_text = ""
    model_used = body.model or "default"
    tokens = 0
    cost = 0.0

    for event in reversed(events):
        if event.type == "message" and getattr(event, "role", "") == "assistant":
            response_text = getattr(event, "message", "") or ""
            model_used = getattr(event, "model", model_used)
            tokens = getattr(event, "tokens_used", 0)
            cost = getattr(event, "cost", 0.0)
            break

    return ChatResponse(
        session_id=session.id,
        message=response_text,
        model=model_used,
        tokens_used=tokens,
        cost=cost,
        exchange_count=len([e for e in events if e.type == "message"]),
    )


@router.post("/stream")
async def stream_message(
    body: ChatRequest,
    request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    _mutation: None = Depends(require_mutation_identity),
) -> EventSourceResponse:
    """Send a chat message and stream the response as it is produced.

    ``ChatFlow.run()`` is already an ``AsyncGenerator[AgentEvent]`` — this
    endpoint streams it directly instead of draining it into a list first
    (which is what ``POST /api/chat`` above does). The first SSE message
    is always a synthetic ``session`` event carrying ``session_id``, so a
    caller starting a brand-new chat (no ``session_id`` in the request)
    learns the id before the first token arrives.

    Native browser ``EventSource`` cannot send a POST body or custom auth
    headers — clients consume this with ``fetch()`` and a manual SSE
    line reader (the "fetch-event-source" pattern), not ``new EventSource()``.
    """
    container = request.app.state.container
    session = await _resolve_session(body, request, state_repo)
    flow = container.build_chat_flow(session=session, model=body.model or None)

    async def event_generator():
        yield {"event": "session", "data": json.dumps({"session_id": session.id})}
        async for event in flow.run(body.message):
            try:
                data = event.model_dump(mode="json")
            except Exception:
                data = {"type": getattr(event, "type", "unknown"), "error": "serialization_failed"}
            yield {"event": event.type, "data": json.dumps(data, default=str)}

    return EventSourceResponse(event_generator())


@router.get("/history", response_model=ChatSessionList)
async def list_chat_sessions(
    request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    limit: int = 20,
    offset: int = 0,
) -> ChatSessionList:
    """List recent chat sessions for the current user."""
    current_user = get_current_user_id(request)
    sessions = await state_repo.list_sessions(user_id=current_user, limit=limit, offset=offset)
    summaries = [
        ChatSessionSummary(
            id=s.id,
            status=s.status.value if hasattr(s.status, "value") else str(s.status),
            message_count=sum(1 for e in s.events if e.type == "message"),
            total_tokens=0,
            total_cost=0.0,
            created_at=s.created_at.isoformat() if hasattr(s, "created_at") else "",
        )
        for s in sessions
    ]
    return ChatSessionList(sessions=summaries, total=len(summaries))


@router.get("/{session_id}")
async def get_chat_session(
    session_id: str, request: Request, state_repo: StateRepositoryPort = Depends(get_state_repo)
):
    """Retrieve a chat session with full message history."""
    session = await state_repo.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    await verify_session_ownership(request, session.user_id)

    messages = [
        {
            "role": getattr(e, "role", ""),
            "content": getattr(e, "message", ""),
            "model": getattr(e, "model", ""),
            "tokens_used": getattr(e, "tokens_used", 0),
            "cost": getattr(e, "cost", 0.0),
        }
        for e in session.events
        if e.type == "message"
    ]
    return {
        "session_id": session.id,
        "status": session.status.value if hasattr(session.status, "value") else str(session.status),
        "messages": messages,
        "exchange_count": len(messages),
    }
