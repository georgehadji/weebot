#!/usr/bin/env python3
"""REST API and WebSocket routes for behavior tracking."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

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
    actions_by_type: Dict[str, int]
    autonomous_count: int
    user_initiated_count: int
    override_count: int
    last_action: Optional[Dict[str, str]]
    summary: str


class SessionSummaryResponse(BaseModel):
    session_id: str
    total_actions: int
    actions_by_type: Dict[str, int]
    start_time: Optional[str]
    end_time: Optional[str]


class OverrideRequest(BaseModel):
    timestamp: str
    reason: str


# Global reporter instance
reporter = BehaviorReporter()


@router.get("/trust", response_model=TrustScoreResponse)
async def get_trust():
    """Get current trust score."""
    return reporter.get_trust_report()


@router.get("/report/today", response_model=DateReportResponse)
async def get_today_report():
    """Get today's behavioral report."""
    return reporter.get_today_report()


@router.get("/report/{date}", response_model=DateReportResponse)
async def get_date_report(date: str):
    """Get report for a specific date (YYYY-MM-DD)."""
    try:
        return reporter.get_date_report(date)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")


@router.get("/recent", response_model=List[BehaviorEventResponse])
async def get_recent_actions(count: int = 10, session_id: Optional[str] = None):
    """Get recent actions."""
    entries = reporter.get_recent_actions(count, session_id)
    
    return [
        BehaviorEventResponse(
            timestamp=e.timestamp,
            event_type=e.action,
            path=e.path,
            session_id=e.session_id,
            agent_version=e.agent_version,
            initiated=e.initiated,
            is_override=e.is_override
        )
        for e in entries
    ]


@router.get("/session/{session_id}", response_model=SessionSummaryResponse)
async def get_session_summary(session_id: str):
    """Get summary for a specific session."""
    return reporter.get_session_summary(session_id)


@router.post("/override")
async def mark_override(request: OverrideRequest):
    """Mark an action as unsanctioned."""
    trust = TrustManager()
    success = trust.mark_override(request.timestamp, request.reason)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Action not found: {request.timestamp}")
    
    return {"success": True, "timestamp": request.timestamp, "reason": request.reason}


@router.post("/watch/start")
async def start_watching(session_id: str, directory: str):
    """Start behavior tracking for a session."""
    from pathlib import Path
    
    watch_path = Path(directory).resolve()
    if not watch_path.exists():
        raise HTTPException(status_code=400, detail=f"Directory not found: {directory}")
    
    # Check if already tracking
    existing = get_tracker(session_id)
    if existing and existing.is_running():
        return {
            "status": "already_running",
            "session_id": session_id,
            "watch_dir": str(existing.watch_dir)
        }
    
    # Create and start tracker
    tracker = create_tracker(session_id, watch_path)
    tracker.start()
    
    return {
        "status": "started",
        "session_id": session_id,
        "watch_dir": str(watch_path)
    }


@router.post("/watch/stop")
async def stop_watching(session_id: str):
    """Stop behavior tracking for a session."""
    tracker = get_tracker(session_id)
    if tracker:
        tracker.stop()
        stop_tracker(session_id)
        return {"status": "stopped", "session_id": session_id}
    
    raise HTTPException(status_code=404, detail=f"No active tracker for session: {session_id}")


@router.get("/watch/status")
async def get_watch_status(session_id: str):
    """Get tracker status for a session."""
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


@router.post("/self-knowledge/regenerate")
async def regenerate_self_knowledge():
    """Regenerate self-knowledge file."""
    gen = SelfKnowledgeGenerator()
    path = gen.save()
    return {"success": True, "path": str(path)}


# WebSocket for real-time behavior events
# Store active WebSocket connections
_ws_connections: List[WebSocket] = []


async def broadcast_event(event: BehaviorEvent):
    """Broadcast event to all connected WebSockets."""
    if not _ws_connections:
        return
    
    message = {
        "type": f"file.{event.event_type}",
        "timestamp": event.timestamp,
        "path": event.path,
        "session_id": event.session_id,
        "agent_version": event.agent_version,
    }
    
    disconnected = []
    for ws in _ws_connections:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    
    # Clean up disconnected
    for ws in disconnected:
        if ws in _ws_connections:
            _ws_connections.remove(ws)


@router.websocket("/ws")
async def behavior_websocket(websocket: WebSocket):
    """WebSocket for real-time behavior events."""
    await websocket.accept()
    _ws_connections.append(websocket)
    
    logger.info(f"Behavior WebSocket connected: {websocket.client}")
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Send current trust score
        trust = reporter.get_trust_report()
        await websocket.send_json({
            "type": "trust.update",
            "score": trust["score_percentage"],
            "total_actions": trust["total_actions"],
            "overrides": trust["overrides"]
        })
        
        # Keep connection alive and handle client messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                message = json.loads(data)
                
                # Handle client commands
                if message.get("action") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
                
                elif message.get("action") == "get_recent":
                    count = message.get("count", 10)
                    entries = reporter.get_recent_actions(count)
                    await websocket.send_json({
                        "type": "recent.actions",
                        "actions": [
                            {
                                "timestamp": e.timestamp,
                                "action": e.action,
                                "path": e.path,
                                "is_override": e.is_override
                            }
                            for e in entries
                        ]
                    })
                
                elif message.get("action") == "get_trust":
                    trust = reporter.get_trust_report()
                    await websocket.send_json({
                        "type": "trust.update",
                        **trust
                    })
                    
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({
                    "type": "keepalive",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
    except WebSocketDisconnect:
        logger.info(f"Behavior WebSocket disconnected: {websocket.client}")
    except Exception as e:
        logger.warning(f"Behavior WebSocket error: {e}")
    finally:
        if websocket in _ws_connections:
            _ws_connections.remove(websocket)


@router.websocket("/ws/session/{session_id}")
async def session_behavior_websocket(websocket: WebSocket, session_id: str):
    """WebSocket for session-specific behavior events."""
    await websocket.accept()
    
    logger.info(f"Session behavior WebSocket connected: {session_id}")
    
    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
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
    
    # Set up event callback to broadcast to WebSockets
    def on_event(event: BehaviorEvent):
        # Schedule broadcast in event loop
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(broadcast_event(event))
        except Exception as e:
            logger.debug(f"Failed to broadcast event: {e}")
    
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
