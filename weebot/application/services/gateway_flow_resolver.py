"""Gateway Flow Resolver — resolves GatewaySessionKeys to flow sessions.

Maps platform conversations to Weebot flow sessions, creating new sessions
when needed and managing TTL/max-session limits.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from weebot.application.ports.gateway_session_store_port import IGatewaySessionStorePort
from weebot.domain.models.gateway_session import GatewaySession, GatewaySessionKey
from weebot.domain.models.session import Session as WeebotSession
from weebot.domain.models.session import SessionStatus

logger = logging.getLogger(__name__)


class GatewayFlowResolver:
    """Resolves gateway messages to flow sessions.

    On each gateway message:
    1. Look up the GatewaySessionKey → existing GatewaySession.
    2. If found, return the associated flow_session_id.
    3. If not found, create a new GatewaySession + Weebot Session and link them.
    4. Touch last_activity_at on every message.
    """

    def __init__(
        self,
        store: IGatewaySessionStorePort,
        session_ttl_seconds: int = 7 * 24 * 60 * 60,
        max_sessions_per_platform: int = 100,
    ) -> None:
        self._store = store
        self._session_ttl_seconds = session_ttl_seconds
        self._max_sessions_per_platform = max_sessions_per_platform

    async def resolve(
        self,
        key: GatewaySessionKey,
        user_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[GatewaySession, str]:
        """Resolve a gateway message to a gateway session and its flow session ID.

        Returns:
            Tuple of (GatewaySession, flow_session_id).
        """
        existing = await self._store.get(key)

        if existing is not None and existing.is_active:
            # Resume existing session
            updated = existing.touch()
            if title:
                updated = updated.model_copy(update={"title": title})
            if user_id:
                updated = updated.model_copy(update={"user_id": user_id})
            await self._store.upsert(updated)
            logger.debug("Resumed gateway session: %s → flow %s", key.composite_key(), updated.flow_session_id)
            return updated, updated.flow_session_id

        # Create new session
        flow_session_id = f"gw-{key.platform}-{key.chat_id}-{uuid.uuid4().hex[:8]}"

        session = GatewaySession(
            key=key,
            flow_session_id=flow_session_id,
            title=title,
            user_id=user_id,
            metadata=metadata or {},
        )

        # Enforce platform max sessions
        await self._enforce_platform_limit(key.platform)

        await self._store.upsert(session)
        logger.info(
            "Created gateway session: %s → flow %s",
            key.composite_key(), flow_session_id,
        )
        return session, flow_session_id

    async def close(self, key: GatewaySessionKey) -> None:
        """Close a gateway session."""
        await self._store.close_session(key)
        logger.info("Closed gateway session: %s", key.composite_key())

    async def _enforce_platform_limit(self, platform: str) -> None:
        """Remove oldest inactive sessions if platform exceeds max."""
        if self._max_sessions_per_platform <= 0:
            return

        sessions = await self._store.list(platform=platform, active_only=True)
        if len(sessions) > self._max_sessions_per_platform:
            # Sort by last_activity_at ascending and close the oldest
            sorted_sessions = sorted(sessions, key=lambda s: s.last_activity_at)
            to_close = sorted_sessions[:len(sorted_sessions) - self._max_sessions_per_platform + 1]
            for s in to_close:
                await self._store.close_session(s.key)
                logger.info("Closed oldest gateway session (limit): %s", s.key.composite_key())
