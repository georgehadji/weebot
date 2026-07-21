"""Canonical error codes for the Weebot REST API.

Usage::

    from weebot.interfaces.web.error_codes import ErrorCode
    raise HTTPException(
        status_code=404,
        detail="Session not found",
        headers={"X-Error-Code": ErrorCode.SESSION_NOT_FOUND},
    )
"""
from __future__ import annotations


class ErrorCode:
    """Machine-readable error codes returned in the ``X-Error-Code`` response header."""

    # ── Session ─────────────────────────────────────────────────────────
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_ALREADY_RUNNING = "SESSION_ALREADY_RUNNING"
    SESSION_NOT_WAITING = "SESSION_NOT_WAITING"
    SESSION_NO_PROMPT = "SESSION_NO_PROMPT"
    SESSION_DELETE_FAILED = "SESSION_DELETE_FAILED"

    # ── Auth ────────────────────────────────────────────────────────────
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"

    # ── General ─────────────────────────────────────────────────────────
    INTERNAL_ERROR = "INTERNAL_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
