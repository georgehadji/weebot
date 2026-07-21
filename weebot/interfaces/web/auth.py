"""Authentication helpers for web API routers.

Provides dependency-injectable functions to extract the authenticated
user identity from the current request, and to verify session ownership.
"""
from __future__ import annotations

import hashlib
import logging
import os

from fastapi import HTTPException, Request

from weebot.interfaces.web.error_codes import ErrorCode

logger = logging.getLogger(__name__)


def _enforce_ownership() -> bool:
    """Check the WEEBOT_ENFORCE_SESSION_OWNERSHIP feature flag."""
    val = os.environ.get("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true").lower()
    return val not in ("0", "false", "no", "off")


def get_current_user_id(request: Request) -> str:
    """Extract or derive the authenticated user ID from the current request.

    When API key auth is enabled (``X-API-Key`` header is present), we
    derive a stable pseudo-anonymous user ID from the key itself via SHA-256.
    This prevents callers with different keys from seeing each other's sessions
    without exposing the raw key.

    When no API key is supplied, returns ``"anonymous"``.
    """
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        # Derive a stable, non-reversible user ID from the API key
        return f"key-{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    return "anonymous"


async def verify_session_ownership(
    request: Request,
    session_user_id: str | None,
) -> None:
    """Raise ``HTTPException(404)`` if the current user does not own the session.

    Returns silently when:
    - Ownership enforcement is disabled via env var
    - The session has no ``user_id`` (legacy sessions)
    - The caller's user_id matches ``session_user_id``

    We return 404 (not 403) to avoid leaking whether the session exists.
    """
    if not _enforce_ownership():
        return

    current_user = get_current_user_id(request)

    # Legacy sessions without a user_id are accessible by anyone
    if not session_user_id:
        logger.debug(
            "Session has no user_id — skipping ownership check (user=%s)",
            current_user,
        )
        return

    if current_user == session_user_id:
        return  # Own session — allowed

    logger.warning(
        "Session ownership mismatch: current_user=%s session_user_id=%s",
        current_user,
        session_user_id,
    )
    raise HTTPException(
        status_code=404,
        detail="Session not found",
        headers={"X-Error-Code": ErrorCode.SESSION_NOT_FOUND},
    )
