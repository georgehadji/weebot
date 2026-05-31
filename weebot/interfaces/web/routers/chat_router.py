"""Chat REST API router — conversational chat endpoints.

Provides:
  POST /api/chat       — send a message, get LLM response
  GET /api/chat/history — list chat sessions
  GET /api/chat/{id}   — retrieve session details
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
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


@router.post("", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    request: Request,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
) -> ChatResponse:
    """Send a chat message and receive the LLM response."""
    container = request.app.state.container

    # Load or create session
    if body.session_id:
        session = await state_repo.load_session(body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        import uuid
        session = Session(
            id=f"chat-{uuid.uuid4().hex[:8]}",
            user_id="web-user",
            agent_id="chat-agent",
        )
        await state_repo.save_session(session)

    # Build and run the chat flow
    flow = container.build_chat_flow(
        session=session,
        model=body.model or None,
    )
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


@router.get("/history", response_model=ChatSessionList)
async def list_chat_sessions(
    state_repo: StateRepositoryPort = Depends(get_state_repo),
    limit: int = 20,
    offset: int = 0,
) -> ChatSessionList:
    """List recent chat sessions."""
    sessions = await state_repo.list_sessions(
        user_id="web-user",
        limit=limit,
        offset=offset,
    )
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
    session_id: str,
    state_repo: StateRepositoryPort = Depends(get_state_repo),
):
    """Retrieve a chat session with full message history."""
    session = await state_repo.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

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
