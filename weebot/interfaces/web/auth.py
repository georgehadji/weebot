"""Authentication helpers for web API routers.

Provides dependency-injectable functions to extract the authenticated
user identity from the current request, and to verify session ownership.

Supports two auth modes (``WEEBOT_AUTH_MODE``):

- ``legacy`` (default) — single shared ``WEEBOT_API_KEY``.  Identity is
  derived via SHA-256 of the key.  All valid keys map to a single principal.
- ``store`` — multi-principal.  Keys are stored in the ``api_keys`` table
  as salted scrypt hashes.  Identity resolves to the actual ``principal_id``.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from fastapi import HTTPException, Request, Depends

from weebot.application.ports.api_key_port import ApiKeyPort
from weebot.interfaces.web.error_codes import ErrorCode

logger = logging.getLogger(__name__)

_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def _auth_mode() -> str:
    return os.environ.get("WEEBOT_AUTH_MODE", "legacy").lower()


def _is_legacy_mode() -> bool:
    return _auth_mode() == "legacy"


def _get_legacy_api_key() -> str | None:
    """Return the single shared API key, or None."""
    return os.environ.get("WEEBOT_API_KEY", "") or None


def get_current_user_id(request: Request) -> str:
    """Extract or derive the authenticated user ID from the current request.

    In legacy mode (default), this is a synchronous FastAPI dependency:
    derives a stable pseudo-anonymous user ID from the API key itself
    via SHA-256 (as before).

    In store mode, callers should use :func:`get_current_user_id_async`
    instead, which resolves through the ``ApiKeyPort``.

    When no API key is supplied, returns ``"anonymous"``.
    """
    if _is_legacy_mode():
        api_key = request.headers.get("X-API-Key", "")
        if api_key:
            return f"key-{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        return "anonymous"

    # In store mode, the sync version falls back to legacy derivation.
    # Callers that need real principal resolution should use the async version.
    legacy_key = _get_legacy_api_key()
    api_key = request.headers.get("X-API-Key", "")
    if api_key and legacy_key and api_key == legacy_key:
        logger.warning(
            "Auth via legacy WEEBOT_API_KEY (deprecated). "
            "Set WEEBOT_AUTH_MODE=store and issue per-principal keys."
        )
        return f"key-{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    return "anonymous"


async def get_current_user_id_async(
    request: Request,
    api_key_port: ApiKeyPort | None = None,
) -> str:
    """Async version that resolves through the ``ApiKeyPort``.

    FastAPI Dependency: use this on endpoints that need real
    multi-principal identity.  Falls back to legacy derivation
    when the port is not wired or auth mode is ``legacy``.
    """
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        return "anonymous"

    if _is_legacy_mode() or api_key_port is None:
        return get_current_user_id(request)

    # Store mode: lookup by SHA-256, verify with scrypt+salt
    from weebot.infrastructure.security.sqlite_api_key_store import (
        SQLiteApiKeyStore,
        _lookup_hash,
        _verify_key,
    )
    lookup = _lookup_hash(api_key)
    store = SQLiteApiKeyStore()
    try:
        record = await store.load_by_lookup_hash(lookup)
        if record is not None and record.is_valid:
            if _verify_key(api_key, record.key_hash, record.salt):
                try:
                    await store.touch_last_used(record.id)
                except Exception:
                    pass
                return record.principal_id
    finally:
        await store.close()

    # Fall back to legacy check for backward compat during migration
    legacy_key = _get_legacy_api_key()
    if legacy_key and api_key == legacy_key:
        logger.warning(
            "Auth via legacy WEEBOT_API_KEY (deprecated) — store mode without matching key."
        )
        return get_current_user_id(request)

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

    In store mode, resolves through the ``ApiKeyPort`` so multi-principal
    isolation is enforced (different keys mean different principals).
    """
    if not _enforce_ownership():
        return

    current_user = await _resolve_user(request)

    if not session_user_id:
        logger.debug(
            "Session has no user_id — skipping ownership check (user=%s)",
            current_user,
        )
        return

    if current_user == session_user_id:
        return

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


async def require_mutation_identity(request: Request) -> None:
    """Reject mutating requests from anonymous non-loopback callers.

    Intended for use as a FastAPI dependency on mutating endpoints.
    """
    current_user = await _resolve_user(request)
    if current_user == "anonymous":
        client_host = request.client.host if request.client else ""
        if client_host not in _LOOPBACK:
            raise HTTPException(
                status_code=403,
                detail="Mutating requests require authentication",
                headers={"X-Error-Code": ErrorCode.AUTHENTICATION_REQUIRED},
            )


async def _resolve_user(request: Request) -> str:
    """Resolve the authenticated user ID, using the port in store mode.

    In legacy mode, uses SHA-256 derivation (sync, fast).
    In store mode, hashes the key and looks up the principal_id
    via ``ApiKeyPort``.
    """
    if _is_legacy_mode():
        return get_current_user_id(request)

    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        return "anonymous"

    # Store mode: lookup by SHA-256, verify with scrypt+salt
    from weebot.infrastructure.security.sqlite_api_key_store import (
        SQLiteApiKeyStore,
        _lookup_hash,
        _verify_key,
    )
    lookup = _lookup_hash(api_key)
    store = SQLiteApiKeyStore()
    try:
        record = await store.load_by_lookup_hash(lookup)
        if record is not None and record.is_valid:
            if _verify_key(api_key, record.key_hash, record.salt):
                try:
                    await store.touch_last_used(record.id)
                except Exception:
                    pass
                return record.principal_id
    finally:
        await store.close()

    # Fall back to legacy check for backward compat during migration
    legacy_key = _get_legacy_api_key()
    if legacy_key and api_key == legacy_key:
        logger.warning(
            "Auth via legacy WEEBOT_API_KEY (deprecated). "
            "Set WEEBOT_AUTH_MODE=store and issue per-principal keys."
        )
        return get_current_user_id(request)

    return "anonymous"


def _enforce_ownership() -> bool:
    val = os.environ.get("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true").lower()
    return val not in ("0", "false", "no", "off")
