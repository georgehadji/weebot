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
import hmac
import logging
import os

from fastapi import HTTPException, Request, WebSocket
from starlette.requests import HTTPConnection

from weebot.application.ports.api_key_port import ApiKeyPort
from weebot.core.api_key_crypto import lookup_hash, verify_key
from weebot.interfaces.web.error_codes import ErrorCode

logger = logging.getLogger(__name__)

_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# Offered by the UI next to `bearer.<key>`; the server echoes this, never the key.
WS_PROTOCOL = "weebot.v1"


def _offered_protocols(websocket: HTTPConnection) -> list[str]:
    headers = getattr(websocket, "headers", None)
    header = headers.get("sec-websocket-protocol", "") if headers is not None else ""
    return [p.strip() for p in header.split(",")] if isinstance(header, str) else []


def accepted_subprotocol(websocket: WebSocket) -> str | None:
    """The subprotocol to answer the handshake with, so a browser that offered some keeps
    the connection. Prefers the marker over echoing a protocol that carries the key."""
    offered = _offered_protocols(websocket)
    if WS_PROTOCOL in offered:
        return WS_PROTOCOL
    return next((p for p in offered if p.startswith("bearer.")), None)


def _auth_mode() -> str:
    return os.environ.get("WEEBOT_AUTH_MODE", "legacy").lower()


def _behind_proxy() -> bool:
    """True when a reverse proxy (the UI's) fronts this API (WEEBOT_BEHIND_PROXY=1).

    Every proxied request then arrives from loopback, so loopback says nothing about who
    asked and cannot stand in for an identity.
    """
    from weebot.config.secret_accessor import SecretAccessor

    value = (SecretAccessor.get("WEEBOT_BEHIND_PROXY") or "").strip().lower()
    return value in ("1", "true", "yes", "on")


def _is_legacy_mode() -> bool:
    return _auth_mode() == "legacy"


def _get_legacy_api_key() -> str | None:
    """Return the single shared API key, or None."""
    return os.environ.get("WEEBOT_API_KEY", "") or None


def _presented_key(conn: HTTPConnection) -> str:
    """The API key a caller presented, from wherever its transport can carry one.

    Any connection: the X-API-Key header, else an Authorization Bearer. WebSocket also: a
    `bearer.<key>` subprotocol (what a browser can send), or the deprecated ?token=.
    Browsers cannot set headers on a WebSocket, so reading only X-API-Key made every
    browser socket anonymous.
    """
    key = conn.headers.get("X-API-Key", "")
    if key:
        return key
    auth = conn.headers.get("authorization", "")
    if isinstance(auth, str) and auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    scope = getattr(conn, "scope", None)
    if not isinstance(scope, dict) or scope.get("type") != "websocket":
        return ""
    for proto in _offered_protocols(conn):
        if proto.startswith("bearer."):
            return proto[len("bearer."):]
    token = conn.query_params.get("token") or ""
    if token:
        logger.warning(
            "WebSocket key sent as ?token= (deprecated, the key lands in access logs). "
            "Offer the subprotocol bearer.<key> instead."
        )
    return token


def _derived_principal(api_key: str) -> str:
    """The stable pseudo-anonymous principal for a *verified* key."""
    return f"key-{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"


def _client_host(conn: HTTPConnection) -> str:
    client = getattr(conn, "client", None)
    return client.host if client else ""


def _key_store(request: HTTPConnection) -> ApiKeyPort | None:
    """The key store the app's lifespan put on ``app.state`` (None when not wired).

    One store per process, built by the composition root. Before, each
    authenticated request built its own store and opened its own connection.
    """
    return getattr(request.app.state, "api_key_store", None)


async def _principal_from_key(api_key: str, keys: ApiKeyPort) -> str | None:
    """The principal a presented key belongs to, or None.

    Lookup by SHA-256, verification by scrypt and salt (``core.api_key_crypto``);
    an expired or revoked record never verifies.
    """
    record = await keys.load_by_lookup_hash(lookup_hash(api_key))
    if record is None or not record.is_valid:
        return None
    if not verify_key(api_key, record.key_hash, record.salt):
        return None
    try:
        await keys.touch_last_used(record.id)
    except Exception:
        # Bookkeeping only: a failed timestamp must not turn a valid key away.
        logger.warning("could not record last use of API key %s", record.id, exc_info=True)
    return record.principal_id


def get_current_user_id(request: Request) -> str:
    """Extract or derive the authenticated user ID from the current request.

    In legacy mode (default), this is a synchronous FastAPI dependency:
    derives a stable pseudo-anonymous user ID via SHA-256 from an API key
    that matched the configured ``WEEBOT_API_KEY``.

    In store mode, callers should use :func:`get_current_user_id_async`
    instead, which resolves through the ``ApiKeyPort``.

    Returns ``"anonymous"`` when no API key is supplied, when the supplied
    key does not match, and when no key is configured at all.
    """
    if _is_legacy_mode():
        # This branch used to derive a principal from ANY non-empty header
        # value without ever calling _get_legacy_api_key() -- the store-mode
        # branch six lines below always compared, this one never did. So the
        # function named "get_current_user_id" authenticated nothing, and
        # require_mutation_identity, whose whole job is to reject callers
        # without an identity, was satisfied by an arbitrary string.
        #
        # In practice APIKeyMiddleware (interfaces/web/main.py:441-462) had
        # already rejected such a request with 401 before any endpoint
        # dependency ran, and _websocket_auth guards the socket path, so this
        # was not reachable as an unauthenticated bypass on a default
        # deployment -- verified by the tests below. It was reachable with
        # WEEBOT_API_KEY unset and web_require_auth false, where the operator
        # has opened reads deliberately and could still reasonably believe
        # mutations stayed gated.
        #
        # Either way, a function whose safety comes entirely from a middleware
        # installed somewhere else is one new call site away from being wrong:
        # any endpoint on an exempt path, any new WebSocket handler, anything
        # outside the app. It compares now.
        api_key = _presented_key(request)
        legacy_key = _get_legacy_api_key()
        if not api_key or not legacy_key:
            # No key configured means no principal can be minted. Fail closed:
            # every caller is anonymous, and require_mutation_identity keeps
            # mutations to loopback.
            return "anonymous"
        if hmac.compare_digest(api_key, legacy_key):
            return _derived_principal(api_key)
        return "anonymous"

    # In store mode, the sync version falls back to legacy derivation.
    # Callers that need real principal resolution should use the async version.
    legacy_key = _get_legacy_api_key()
    api_key = _presented_key(request)
    if api_key and legacy_key and hmac.compare_digest(api_key, legacy_key):
        logger.warning(
            "Auth via legacy WEEBOT_API_KEY (deprecated). "
            "Set WEEBOT_AUTH_MODE=store and issue per-principal keys."
        )
        return _derived_principal(api_key)
    return "anonymous"


async def get_current_user_id_async(
    request: Request, api_key_port: ApiKeyPort | None = None
) -> str:
    """Async version that resolves through the ``ApiKeyPort``.

    FastAPI Dependency: use this on endpoints that need real
    multi-principal identity.  Falls back to legacy derivation
    when the port is not wired or auth mode is ``legacy``.
    """
    api_key = _presented_key(request)
    if not api_key:
        return "anonymous"

    keys = api_key_port if api_key_port is not None else _key_store(request)
    if _is_legacy_mode() or keys is None:
        return get_current_user_id(request)

    principal = await _principal_from_key(api_key, keys)
    if principal is not None:
        return principal

    # Fall back to legacy check for backward compat during migration
    legacy_key = _get_legacy_api_key()
    if legacy_key and hmac.compare_digest(api_key, legacy_key):
        logger.warning(
            "Auth via legacy WEEBOT_API_KEY (deprecated) — store mode without matching key."
        )
        return get_current_user_id(request)

    return "anonymous"


async def authenticate(conn: HTTPConnection, legacy_key: str | None = None) -> str | None:
    """Who is calling, by the one rule every HTTP route, the middleware and every socket use.

    Returns the caller's principal; "anonymous" for a local caller when no legacy key is
    configured (what FailClosedMiddleware and the sockets always allowed); or None when
    the caller must be refused. A presented key resolves through the key store in store
    mode, else against the legacy key (*legacy_key*, default ``WEEBOT_API_KEY``). A key
    that matches nothing is refused, unless there is nothing to match it against.
    """
    legacy_key = legacy_key if legacy_key is not None else _get_legacy_api_key()
    key = _presented_key(conn)
    # The middleware and then the route dependency ask for the same request: one scrypt
    # check, not two. The answer lives on the request scope, so it dies with the request.
    scope = getattr(conn, "scope", None)
    cache = scope.setdefault("weebot.auth", {}) if isinstance(scope, dict) else {}
    if (key, legacy_key) not in cache:
        cache[(key, legacy_key)] = await _authenticate(conn, key, legacy_key)
    return cache[(key, legacy_key)]


async def _authenticate(conn: HTTPConnection, key: str, legacy_key: str | None) -> str | None:
    store_mode = not _is_legacy_mode()
    if key:
        if store_mode and (keys := _key_store(conn)) is not None:
            principal = await _principal_from_key(key, keys)
            if principal is not None:
                return principal
        if legacy_key and hmac.compare_digest(key, legacy_key):
            if store_mode:
                logger.warning(
                    "Auth via legacy WEEBOT_API_KEY (deprecated). "
                    "Set WEEBOT_AUTH_MODE=store and issue per-principal keys."
                )
            return _derived_principal(key)
        if legacy_key or store_mode:
            return None
    elif legacy_key:
        return None
    return "anonymous" if _client_host(conn) in _LOOPBACK else None


async def verify_session_ownership(request: Request, session_user_id: str | None) -> None:
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
        logger.debug("Session has no user_id — skipping ownership check (user=%s)", current_user)
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
        if client_host not in _LOOPBACK or _behind_proxy():
            raise HTTPException(
                status_code=403,
                detail="Mutating requests require authentication",
                headers={"X-Error-Code": ErrorCode.AUTHENTICATION_REQUIRED},
            )


async def _resolve_user(request: Request) -> str:
    """The caller's user ID for ownership and mutation checks ("anonymous" when none)."""
    return (await authenticate(request)) or "anonymous"


def _enforce_ownership() -> bool:
    val = os.environ.get("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true").lower()
    return val not in ("0", "false", "no", "off")
