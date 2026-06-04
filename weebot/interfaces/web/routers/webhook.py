"""Generic webhook gateway — receives external messages via HTTP POST.

Accepts JSON payloads from any external service (Zapier, n8n, custom scripts)
and routes them through a PlanActFlow for processing.  Responses are returned
synchronously.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from weebot.application.di import Container
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.event import AgentEvent
from weebot.domain.models.session import Session, SessionStatus
from weebot.interfaces.factories import build_tools, create_flow
from weebot.interfaces.gateways.base import GatewayMessage, GatewayResponse
# Lazy import: ToolCollection imported inside handler functions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhook"])


class WebhookRequest(BaseModel):
    """Incoming webhook payload."""
    text: str = Field(..., description="The message or task description")
    session_id: Optional[str] = Field(default=None, description="Optional session ID for continuation")
    model: Optional[str] = Field(default=None, description="Optional model override")


class WebhookResponse(BaseModel):
    """Synchronous response from the agent."""
    response: str = Field(default="")
    session_id: str = Field(default="")
    status: str = Field(default="")
    tool_calls: int = Field(default=0)


@router.post("/run")
async def webhook_run(body: WebhookRequest, request: Request) -> WebhookResponse:
    """Execute a one-shot prompt through PlanActFlow and return the result.

    This is the primary webhook endpoint — POST a message, get a response.
    Sessions are persisted so follow-up messages can reference the same
    session_id for continuation.
    """
    container: Optional[Container] = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="DI container not initialized")

    state_repo = container.get(StateRepositoryPort)
    llm = container.get(LLMPort)

    import uuid

    session_id = body.session_id or f"webhook-{uuid.uuid4().hex[:8]}"

    # Load existing session or create new
    if body.session_id:
        session = await state_repo.load_session(session_id)
        if session is None:
            session = Session(
                id=session_id, user_id="webhook", agent_id="webhook-agent",
            )
    else:
        session = Session(
            id=session_id, user_id="webhook", agent_id="webhook-agent",
        )

    # Build tools and flow
    tools = await build_tools(role="admin")
    flow = create_flow(
        flow_type="plan_act",
        session=session,
        llm=llm,
        tools=tools,
        state_repo=state_repo,
        model=body.model,
    )

    # Run and collect response
    response_text = ""
    tool_count = 0
    event_count = 0

    async for event in flow.run(body.text):
        event_count += 1
        if getattr(event, "type", "") == "message":
            msg = getattr(event, "message", "")
            if msg:
                response_text = msg
        if getattr(event, "type", "") == "tool":
            tool_count += 1

    if flow.is_done():
        status = "completed"
    else:
        status = "pending"

    return WebhookResponse(
        response=response_text or "(no response produced)",
        session_id=session_id,
        status=status,
        tool_calls=tool_count,
    )
