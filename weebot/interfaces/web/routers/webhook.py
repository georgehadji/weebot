"""Generic webhook gateway — receives external messages via HTTP POST.

Accepts JSON payloads from any external service (Zapier, n8n, custom scripts)
and routes them through a PlanActFlow for processing.  Responses are returned
synchronously.
"""

from __future__ import annotations

import hmac as _hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from weebot.application.di import Container
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session
from weebot.interfaces.factories import run_scope

# Lazy import: ToolCollection imported inside handler functions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

from weebot.interfaces.web.auth import _LOOPBACK  # noqa: E402 -- one loopback set


async def require_webhook_auth(request: Request) -> None:
    """FastAPI dependency: authenticate webhook requests.

    Priority:
    1. ``webhook_api_key`` from settings → require ``X-Webhook-Key`` header.
    2. Global ``weebot_api_key`` → require ``X-API-Key`` header (existing auth).
    3. Neither → allow loopback only (local dev).
    """
    from weebot.config.settings import get_settings

    _settings = get_settings()

    if _settings.webhook_api_key:
        header_key = request.headers.get("X-Webhook-Key", "")
        if not _hmac.compare_digest(header_key, _settings.webhook_api_key):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized — provide valid X-Webhook-Key header",
                headers={"X-Error-Code": "UNAUTHORIZED"},
            )
        return

    if _settings.weebot_api_key:
        header_key = request.headers.get("X-API-Key", "")
        if not _hmac.compare_digest(header_key, _settings.weebot_api_key):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized — provide valid X-API-Key header",
                headers={"X-Error-Code": "UNAUTHORIZED"},
            )
        return

    # No key configured — only allow loopback
    client_host = request.client.host if request.client else ""
    if client_host not in _LOOPBACK:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized — no webhook API key configured",
            headers={"X-Error-Code": "UNAUTHORIZED"},
        )


class WebhookRequest(BaseModel):
    """Incoming webhook payload."""

    text: str = Field(..., description="The message or task description")
    session_id: str | None = Field(default=None, description="Optional session ID for continuation")
    model: str | None = Field(default=None, description="Optional model override")


class WebhookResponse(BaseModel):
    """Synchronous response from the agent."""

    response: str = Field(default="")
    session_id: str = Field(default="")
    status: str = Field(default="")
    tool_calls: int = Field(default=0)


@router.post("/run")
async def webhook_run(
    body: WebhookRequest, request: Request, _auth: None = Depends(require_webhook_auth)
) -> WebhookResponse:
    """Execute a one-shot prompt through PlanActFlow and return the result.

    This is the primary webhook endpoint — POST a message, get a response.
    Sessions are persisted so follow-up messages can reference the same
    session_id for continuation.
    """
    from weebot.config.settings import get_settings

    container: Container | None = getattr(request.app.state, "container", None)
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
            session = Session(id=session_id, user_id="webhook", agent_id="webhook-agent")
        elif session.user_id != "webhook":
            # The webhook key is not a user's identity: continue only webhook
            # sessions, and 404 (not 403) so others' ids do not leak (F57).
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    else:
        session = Session(id=session_id, user_id="webhook", agent_id="webhook-agent")

    # Determine tool role based on exec-tools setting
    _settings = get_settings()
    tool_role = "admin" if _settings.webhook_allow_exec_tools else "webhook"
    # Run and collect response
    response_text = ""
    tool_count = 0
    event_count = 0

    from weebot.application.services.tool_approval import DenyApproval, approval_scope

    async with run_scope(
        session, llm=llm, state_repo=state_repo, role=tool_role, model=body.model
    ) as flow:
        # A webhook caller cannot answer an approval prompt (ADR-013): Deny.
        with approval_scope(approval=DenyApproval()):
            events = [event async for event in flow.run(body.text)]
        done = flow.is_done()
    for event in events:
        event_count += 1
        if getattr(event, "type", "") == "message":
            msg = getattr(event, "message", "")
            if msg:
                response_text = msg
        if getattr(event, "type", "") == "tool":
            tool_count += 1

    if done:
        status = "completed"
    else:
        status = "pending"

    return WebhookResponse(
        response=response_text or "(no response produced)",
        session_id=session_id,
        status=status,
        tool_calls=tool_count,
    )
