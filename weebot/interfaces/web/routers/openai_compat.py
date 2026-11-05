"""OpenAI-compatible API (H12b), mounted at ``/v1`` when ``WEEBOT_OPENAI_API_ENABLED`` is set.

``/v1/chat/completions`` starts or continues a Weebot session and streams its events as
``chat.completion.chunk``s; ``/v1/runs`` is the same run with its events, approvals and stop
exposed. Auth, rate tier and session ownership are the web API's own, so a client sees only its
own sessions. Client-supplied ``tools`` are refused: Weebot runs its own.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.idempotency_port import IdempotencyPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.services.session_title import derive_session_title
from weebot.interfaces.web import openai_adapter as adapter
from weebot.interfaces.web.auth import (
    current_principal,
    require_mutation_identity,
    verify_session_ownership,
)
from weebot.interfaces.web.bounded_drop_oldest_queue import BoundedDropOldestQueue
from weebot.interfaces.web.event_visibility import EventVisibility
from weebot.interfaces.web.routers import sessions as sessions_routes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["openai"])

RUN_DEADLINE_SECONDS = 30 * 60
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class _Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: Any = ""


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[_Message] = Field(min_length=1)
    stream: bool = False
    user: str | None = None
    tools: list[Any] | None = None
    functions: list[Any] | None = None


class RunRequest(BaseModel):
    input: str = Field(min_length=1)
    model: str = "weebot-plan"
    session_id: str | None = None


class ApprovalRequest(BaseModel):
    call_id: str = Field(min_length=1)
    decision: str = Field(pattern="^(approve|deny)$")
    scope: str = Field(default="once", pattern="^(once|session|always)$")


async def _state_repo(request: Request) -> StateRepositoryPort:
    return request.app.state.container.get(StateRepositoryPort)


def _persona_ids() -> list[str]:
    try:
        from pathlib import Path

        from weebot.agents.registry import AgentRegistry

        return sorted(p.persona_id for p in AgentRegistry(Path.cwd()).list_personas())
    except Exception:
        logger.warning("personas unavailable for /v1/models", exc_info=True)
        return []


def _show_steps() -> bool:
    from weebot.config.settings import get_settings

    return get_settings().openai_api_show_steps


def _check_id(value: str) -> str:
    if not _ID.match(value):
        raise HTTPException(status_code=400, detail="session id has characters not allowed")
    return value


class _Tap:
    """The events of one session, from before the run starts until it stops."""

    def __init__(self, bus: EventBusPort, session_id: str) -> None:
        self._bus, self._session_id = bus, session_id
        self.queue: BoundedDropOldestQueue[Any] = BoundedDropOldestQueue(maxsize=1000)
        bus.subscribe(self._on_event)

    async def _on_event(self, event: Any) -> None:
        if getattr(event, "session_id", "") == self._session_id:
            self.queue.try_put(event)

    def close(self) -> None:
        self._bus.unsubscribe(self._on_event)

    async def events(self) -> AsyncIterator[Any]:
        """Events until the first terminal one, or the deadline. Closes the tap."""
        deadline = time.monotonic() + RUN_DEADLINE_SECONDS
        try:
            while (left := deadline - time.monotonic()) > 0:
                try:
                    event = await asyncio.wait_for(self.queue.get(), timeout=left)
                except TimeoutError:
                    return
                if event is None:
                    return
                yield event
                if adapter.is_terminal(event):
                    return
        finally:
            self.close()


async def _load_owned(request: Request, repo: StateRepositoryPort, session_id: str) -> Session:
    session = await repo.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await verify_session_ownership(request, session.user_id)
    return session


async def _begin(
    request: Request,
    repo: StateRepositoryPort,
    *,
    text: str,
    model: str,
    session_id: str | None,
) -> tuple[Session, _Tap]:
    """Create or continue a session, start its run, and return it with its event tap."""
    chosen = adapter.resolve_model(model, _persona_ids())
    if chosen is None:
        raise HTTPException(status_code=404, detail=f"The model '{model}' does not exist")
    mode, persona = chosen
    principal = await current_principal(request)
    existing = None
    if session_id:
        existing = await repo.load_session(_check_id(session_id))
        if existing is not None:
            await verify_session_ownership(request, existing.user_id)
    session = existing or Session(
        id=session_id or str(uuid.uuid4()),
        user_id=principal,
        agent_id=persona or "weebot-web",
        title=derive_session_title(text) or None,
        context={"last_prompt": text, "execution_mode": mode},
    )
    if existing is None and not await repo.create_session(session):
        raise HTTPException(status_code=409, detail=f"Session {session.id} already exists")
    tap = _Tap(request.app.state.container.get(EventBusPort), session.id)
    try:
        result = await sessions_routes._dispatch_input(
            request, session, text, repo, execution_mode=mode
        )
    except BaseException:
        tap.close()
        raise
    return result.session, tap


async def _usage(request: Request, session_id: str) -> dict[str, Any]:
    cost = None
    try:
        from weebot.application.di.keys import SESSION_COST_METER

        cost = request.app.state.container.get(SESSION_COST_METER).total(session_id)
    except Exception:
        logger.debug("cost meter unavailable for %s", session_id, exc_info=True)
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": cost}


@router.get("/models")
async def list_models() -> dict[str, Any]:
    return adapter.model_list(_persona_ids(), int(time.time()))


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    body: ChatRequest,
    x_weebot_session: str | None = Header(default=None),
    repo: StateRepositoryPort = Depends(_state_repo),
    _mutation: None = Depends(require_mutation_identity),
):
    if body.tools or body.functions:
        raise HTTPException(status_code=400, detail="tools are not supported; Weebot runs its own")
    text = next(
        (adapter.message_text(m.content) for m in reversed(body.messages) if m.role == "user"), ""
    )
    if not text.strip():
        raise HTTPException(status_code=400, detail="messages need a user message with text")
    session, tap = await _begin(
        request, repo, text=text, model=body.model, session_id=x_weebot_session or body.user
    )
    cid, created, show = f"chatcmpl-{uuid.uuid4().hex}", int(time.time()), _show_steps()

    if body.stream:

        async def sse() -> AsyncIterator[str]:
            yield f"data: {json.dumps(adapter.role_chunk(cid, body.model, created))}\n\n"
            async for event in tap.events():
                chunk = adapter.to_openai_chunk(
                    event, completion_id=cid, model=body.model, created=created, show_steps=show
                )
                if chunk is not None:
                    yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={"X-Weebot-Session": session.id, "Cache-Control": "no-cache"},
        )

    parts = [t async for e in tap.events() if (t := adapter.event_text(e, show)) is not None]
    return JSONResponse(
        adapter.completion_body(
            completion_id=cid,
            model=body.model,
            created=created,
            content="\n\n".join(parts),
            usage=await _usage(request, session.id),
            extra={"session_id": session.id},
        ),
        headers={"X-Weebot-Session": session.id},
    )


def _run_body(session: Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "object": "run",
        "status": session.status.value,
        "created_at": int(session.created_at.timestamp()),
    }


@router.post("/runs")
async def create_run(
    request: Request,
    body: RunRequest,
    idempotency_key: str | None = Header(default=None),
    repo: StateRepositoryPort = Depends(_state_repo),
    _mutation: None = Depends(require_mutation_identity),
) -> dict[str, Any]:
    principal = await current_principal(request)
    store: IdempotencyPort | None = None
    candidate = _check_id(body.session_id or str(uuid.uuid4()))
    if idempotency_key:
        store = request.app.state.container.get(IdempotencyPort)
        winner = await store.put(idempotency_key, principal, candidate)
        if winner != candidate:
            return _run_body(await _load_owned(request, repo, winner))
    try:
        session, tap = await _begin(
            request, repo, text=body.input, model=body.model, session_id=candidate
        )
    except BaseException:
        if store is not None and idempotency_key:
            await store.forget(idempotency_key, principal)
        raise
    tap.close()  # events are read through GET /v1/runs/{id}/events
    return _run_body(session)


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str, request: Request, repo: StateRepositoryPort = Depends(_state_repo)
):
    """Live events of a run, as server-sent events; ends with its terminal event."""
    session = await _load_owned(request, repo, run_id)
    visible = EventVisibility(request, repo)
    tap = _Tap(request.app.state.container.get(EventBusPort), run_id)

    async def stream() -> AsyncIterator[dict[str, str]]:
        if session.status not in (SessionStatus.RUNNING, SessionStatus.PENDING):
            tap.close()
            done = {"type": "done", "session_id": run_id, "status": session.status.value}
            yield {"event": "done", "data": json.dumps(done)}
            return
        async for event in tap.events():
            if not await visible(event):
                continue
            data = event.model_dump(mode="json", by_alias=True)
            kind = getattr(event, "type", "unknown")
            yield {"event": kind, "data": json.dumps(data, default=str)}

    return EventSourceResponse(stream())


@router.post("/runs/{run_id}/approval")
async def run_approval(
    run_id: str,
    request: Request,
    body: ApprovalRequest,
    repo: StateRepositoryPort = Depends(_state_repo),
    _mutation: None = Depends(require_mutation_identity),
) -> dict[str, Any]:
    """Answer the approval a waiting run asked for, with the reply the web UI would send."""
    session = await _load_owned(request, repo, run_id)
    if session.status != SessionStatus.WAITING:
        raise HTTPException(status_code=409, detail=f"run is {session.status.value}, not waiting")
    reply = "no" if body.decision == "deny" else {"once": "yes"}.get(body.scope, body.scope)
    result = await sessions_routes._dispatch_input(request, session, reply, repo)
    return _run_body(result.session)


@router.post("/runs/{run_id}/stop")
async def run_stop(
    run_id: str,
    request: Request,
    repo: StateRepositoryPort = Depends(_state_repo),
    _mutation: None = Depends(require_mutation_identity),
) -> dict[str, Any]:
    await _load_owned(request, repo, run_id)
    stopped = await sessions_routes.cancel_session(run_id, request, repo, None)
    return {"id": stopped.id, "object": "run", "status": stopped.status}
