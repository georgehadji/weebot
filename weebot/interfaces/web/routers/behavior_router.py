#!/usr/bin/env python3
"""REST API and WebSocket routes for behavior tracking."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import Future
from datetime import UTC, datetime
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.config.settings import WORKSPACE_ROOT
from weebot.core.behavior_reporting import BehaviorReporter, LedgerEntry, SelfKnowledgeGenerator
from weebot.core.behavior_tracker import (
    BehaviorEvent,
    BehaviorTracker,
    TrustManager,
    create_tracker,
    get_tracker,
    stop_tracker,
)
from weebot.interfaces.web.auth import (
    accepted_subprotocol,
    current_principal,
    ownership_enforced,
    require_mutation_identity,
    verify_session_ownership,
)
from weebot.interfaces.web.websocket import fan_out

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/behavior", tags=["behavior"])


# Pydantic models for API
class TrustScoreResponse(BaseModel):
    score_percentage: int
    score: float
    total_actions: int
    overrides: int
    last_updated: str
    status: str


class BehaviorEventResponse(BaseModel):
    timestamp: str
    event_type: str
    path: str
    session_id: str
    agent_version: str
    initiated: str
    is_override: bool = False


class DateReportResponse(BaseModel):
    date: str
    total_actions: int
    actions_by_type: dict[str, int]
    autonomous_count: int
    user_initiated_count: int
    override_count: int
    last_action: dict[str, str] | None
    summary: str


class SessionSummaryResponse(BaseModel):
    session_id: str
    total_actions: int
    actions_by_type: dict[str, int]
    start_time: str | None
    end_time: str | None


class OverrideRequest(BaseModel):
    timestamp: str
    reason: str


# Global reporter instance
reporter = BehaviorReporter()


# Each principal sees its own sessions (decision D-BEH); /trust and /report stay aggregate.
async def _session_owner(conn, session_id: str) -> str | None:
    """The user_id of *session_id*, or None when the state repo does not know it."""
    container = getattr(getattr(getattr(conn, "app", None), "state", None), "container", None)
    if container is None or not session_id:
        return None
    session = await container.get(StateRepositoryPort).load_session(session_id)
    return getattr(session, "user_id", None)


async def _require_owner(conn, session_id: str) -> None:
    """404 unless the caller owns *session_id* (or nobody does)."""
    await verify_session_ownership(conn, await _session_owner(conn, session_id))


async def _owned(conn, entries: list[LedgerEntry]) -> list[LedgerEntry]:
    """The entries whose session the caller owns, one ownership lookup per session."""
    allowed: dict[str, bool] = {}
    for entry in entries:
        if entry.session_id not in allowed:
            try:
                await _require_owner(conn, entry.session_id)
                allowed[entry.session_id] = True
            except HTTPException:
                allowed[entry.session_id] = False
    return [e for e in entries if allowed[e.session_id]]


@router.get("/trust", response_model=TrustScoreResponse)
async def get_trust():
    """Get current trust score."""
    return reporter.get_trust_report()


@router.get("/report/today", response_model=DateReportResponse)
async def get_today_report():
    """Get today's behavioral report."""
    return reporter.get_today_report()


@router.get("/report/{date}", response_model=DateReportResponse)
async def get_date_report(date: _date):
    """Get report for a specific date (YYYY-MM-DD; anything else is 422, R22)."""
    try:
        return reporter.get_date_report(date.isoformat())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")


@router.get("/recent", response_model=list[BehaviorEventResponse])
async def get_recent_actions(request: Request, count: int = 10, session_id: str | None = None):
    """Get recent actions of the caller's sessions."""
    if session_id:
        await _require_owner(request, session_id)
        entries = reporter.get_recent_actions(count, session_id)
    else:
        entries = (await _owned(request, reporter.get_recent_actions(max(count, 100))))[:count]

    return [
        BehaviorEventResponse(
            timestamp=e.timestamp,
            event_type=e.action,
            path=e.path,
            session_id=e.session_id,
            agent_version=e.agent_version,
            initiated=e.initiated,
            is_override=e.is_override,
        )
        for e in entries
    ]


@router.get("/session/{session_id}", response_model=SessionSummaryResponse)
async def get_session_summary(session_id: str, request: Request):
    """Get summary for a specific session."""
    await _require_owner(request, session_id)
    return reporter.get_session_summary(session_id)


@router.post("/override", dependencies=[Depends(require_mutation_identity)])
async def mark_override(request: OverrideRequest):
    """Mark an action as unsanctioned."""
    trust = TrustManager()
    success = trust.mark_override(request.timestamp, request.reason)

    if not success:
        raise HTTPException(status_code=404, detail=f"Action not found: {request.timestamp}")

    return {"success": True, "timestamp": request.timestamp, "reason": request.reason}


@router.post("/watch/start", dependencies=[Depends(require_mutation_identity)])
async def start_watching(session_id: str, directory: str, request: Request):
    """Start behavior tracking for a session, on a folder inside the workspace."""
    from pathlib import Path

    await _require_owner(request, session_id)
    watch_path = Path(directory).resolve()
    # The path is not echoed: it would tell a caller what exists outside the workspace.
    if not watch_path.is_relative_to(WORKSPACE_ROOT) or not watch_path.is_dir():
        raise HTTPException(
            status_code=400, detail="directory must be an existing folder inside the workspace"
        )

    # Check if already tracking
    existing = get_tracker(session_id)
    if existing and existing.is_running():
        return {
            "status": "already_running",
            "session_id": session_id,
            "watch_dir": str(existing.watch_dir),
        }

    # Create and start tracker
    tracker = create_tracker(session_id, watch_path)
    tracker.start()

    return {"status": "started", "session_id": session_id, "watch_dir": str(watch_path)}


@router.post("/watch/stop", dependencies=[Depends(require_mutation_identity)])
async def stop_watching(session_id: str, request: Request):
    """Stop behavior tracking for a session."""
    await _require_owner(request, session_id)
    tracker = get_tracker(session_id)
    if tracker:
        tracker.stop()
        stop_tracker(session_id)
        return {"status": "stopped", "session_id": session_id}

    raise HTTPException(status_code=404, detail=f"No active tracker for session: {session_id}")


@router.get("/watch/status")
async def get_watch_status(session_id: str, request: Request):
    """Get tracker status for a session."""
    await _require_owner(request, session_id)
    tracker = get_tracker(session_id)
    if tracker:
        return tracker.get_stats()

    return {"session_id": session_id, "running": False}


@router.get("/self-knowledge")
async def get_self_knowledge():
    """Get agent self-knowledge content."""
    gen = SelfKnowledgeGenerator()
    content = gen.get_content()
    return {"content": content, "path": str(gen.SELF_KNOWLEDGE_FILE)}


@router.post("/self-knowledge/regenerate", dependencies=[Depends(require_mutation_identity)])
async def regenerate_self_knowledge():
    """Regenerate self-knowledge file."""
    gen = SelfKnowledgeGenerator()
    path = gen.save()
    return {"success": True, "path": str(path)}


# WebSocket for real-time behavior events
# Store active WebSocket connections (with lock for concurrent access)
_ws_connections: list[WebSocket] = []
# The principal each /ws client authenticated as; events go only to the session's owner.
_ws_principals: dict[WebSocket, str] = {}
_ws_lock = asyncio.Lock()
_WS_MAX_MSG_SIZE = 1024 * 100  # 100 KB max incoming JSON
# How long one client may take to accept a broadcast before it is dropped.
_WS_SEND_TIMEOUT = 5.0


async def broadcast_event(event: BehaviorEvent):
    """Broadcast event to all connected WebSockets.

    The lock covers the snapshot only, never the sends. It used to wrap the
    whole function, and because the same lock also guards registration (in
    ``behavior_websocket``) and removal (in its ``finally`` block), a client
    whose socket never drained held every one of them: no event could be
    broadcast, no new client could connect, and -- the part that made it
    permanent -- no client could disconnect, because leaving required the lock
    the hang was holding. The one thing that would have cleared it was the one
    thing it blocked.
    """
    async with _ws_lock:
        if not _ws_connections:
            return
        connections = list(_ws_connections)

    if ownership_enforced():
        owner = await _session_owner(connections[0], event.session_id)
        if owner:
            connections = [ws for ws in connections if _ws_principals.get(ws, owner) == owner]
        if not connections:
            return

    message = {
        "type": f"file.{event.event_type}",
        "timestamp": event.timestamp,
        "path": event.path,
        "session_id": event.session_id,
        "agent_version": event.agent_version,
    }

    disconnected = await fan_out(
        connections,
        lambda ws: ws.send_json(message),
        timeout=_WS_SEND_TIMEOUT,
        what="behavior WebSocket",
    )

    if disconnected:
        async with _ws_lock:
            for ws in disconnected:
                if ws in _ws_connections:
                    _ws_connections.remove(ws)


async def _ws_authorized(websocket: WebSocket) -> bool:
    from weebot.config.settings import get_settings
    from weebot.interfaces.web.auth import authenticate

    return await authenticate(websocket, get_settings().weebot_api_key) is not None


@router.websocket("/ws")
async def behavior_websocket(websocket: WebSocket):
    """WebSocket for real-time behavior events."""
    if not await _ws_authorized(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    principal = await current_principal(websocket)
    await websocket.accept(subprotocol=accepted_subprotocol(websocket))
    async with _ws_lock:
        _ws_connections.append(websocket)
        _ws_principals[websocket] = principal

    logger.info(f"Behavior WebSocket connected: {websocket.client}")

    try:
        # Send initial connection message
        await websocket.send_json({"type": "connected", "timestamp": datetime.now(UTC).isoformat()})

        # Send current trust score
        trust = reporter.get_trust_report()
        await websocket.send_json(
            {
                "type": "trust.update",
                "score": trust["score_percentage"],
                "total_actions": trust["total_actions"],
                "overrides": trust["overrides"],
            }
        )

        # Keep connection alive and handle client messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if len(data) > _WS_MAX_MSG_SIZE:
                    await websocket.send_json({"type": "error", "message": "Message too large"})
                    continue
                message = json.loads(data)

                # Handle client commands
                if message.get("action") == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": datetime.now(UTC).isoformat()}
                    )

                elif message.get("action") == "get_recent":
                    count = message.get("count", 10)
                    entries = await _owned(websocket, reporter.get_recent_actions(count))
                    await websocket.send_json(
                        {
                            "type": "recent.actions",
                            "actions": [
                                {
                                    "timestamp": e.timestamp,
                                    "action": e.action,
                                    "path": e.path,
                                    "is_override": e.is_override,
                                }
                                for e in entries
                            ],
                        }
                    )

                elif message.get("action") == "get_trust":
                    trust = reporter.get_trust_report()
                    await websocket.send_json({"type": "trust.update", **trust})

            except TimeoutError:
                # Send keepalive
                await websocket.send_json(
                    {"type": "keepalive", "timestamp": datetime.now(UTC).isoformat()}
                )

    except WebSocketDisconnect:
        logger.info(f"Behavior WebSocket disconnected: {websocket.client}")
    except Exception as e:
        logger.warning(f"Behavior WebSocket error: {e}")
    finally:
        async with _ws_lock:
            if websocket in _ws_connections:
                _ws_connections.remove(websocket)
            _ws_principals.pop(websocket, None)


@router.websocket("/ws/session/{session_id}")
async def session_behavior_websocket(websocket: WebSocket, session_id: str):
    """WebSocket for session-specific behavior events."""
    if not await _ws_authorized(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    try:
        await _require_owner(websocket, session_id)
    except HTTPException:
        await websocket.close(code=4003, reason="Forbidden")
        return

    await websocket.accept(subprotocol=accepted_subprotocol(websocket))

    logger.info(f"Session behavior WebSocket connected: {session_id}")

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("action") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Session behavior WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.warning(f"Session behavior WebSocket error: {e}")


# Integration with session creation
async def start_session_tracking(session_id: str, working_dir: str) -> BehaviorTracker:
    """Start tracking for a new session."""
    from pathlib import Path

    # Set up event callback to broadcast to WebSockets.
    #
    # `on_event` is invoked by watchdog on the observer's own thread, not on
    # the event loop. `asyncio.get_event_loop()` there raises RuntimeError
    # ("no current event loop in thread 'Thread-N'"), which the except below
    # swallowed at DEBUG -- so no event ever reached a connected client, and
    # the list of tasks it was meant to accumulate never gained an entry.
    # `loop.create_task` would have been wrong regardless: it is not
    # thread-safe. Capture the loop here, where one is running, and hand work
    # to it with the cross-thread API.
    loop = asyncio.get_running_loop()
    _tracker_futures: set[Future] = set()

    def _done(fut: Future) -> None:
        _tracker_futures.discard(fut)
        try:
            fut.result()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Behavior broadcast failed: %s", exc)

    def on_event(event: BehaviorEvent):
        try:
            future = asyncio.run_coroutine_threadsafe(broadcast_event(event), loop)
        except RuntimeError as exc:
            # The loop is closed -- the session outlived the server. Nothing to
            # broadcast to, and nothing to retry.
            logger.debug("Behavior broadcast skipped, loop is gone: %s", exc)
            return
        # Held only until the broadcast settles, so the set cannot grow without
        # bound; the callback is what retrieves the exception as well.
        _tracker_futures.add(future)
        future.add_done_callback(_done)

    tracker = create_tracker(session_id, Path(working_dir).resolve(), on_event)
    tracker.start()

    logger.info(f"Started behavior tracking for session {session_id}")
    return tracker


async def stop_session_tracking(session_id: str):
    """Stop tracking for a session."""
    tracker = get_tracker(session_id)
    if tracker:
        tracker.stop()
        stop_tracker(session_id)
        logger.info(f"Stopped behavior tracking for session {session_id}")


if __name__ == "__main__":
    # Quick test
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("Trust report:", reporter.get_trust_report())
        print("Today report:", reporter.get_today_report())
        print("Recent actions:", len(reporter.get_recent_actions(5)))
