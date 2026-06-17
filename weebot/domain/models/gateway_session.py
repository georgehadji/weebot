"""Gateway session domain models — tracks conversation sessions across gateways.

Each GatewaySession maps a platform-specific chat (Telegram chat, Discord channel,
Slack channel, etc.) to a Weebot flow session, allowing conversations to span
multiple messages without losing context.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class GatewayPlatform(str, Enum):
    """Supported gateway platforms."""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    SIGNAL = "signal"
    EMAIL = "email"
    WEB = "web"


class GatewayChatType(str, Enum):
    """Type of chat/conversation on a gateway platform."""
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
    THREAD = "thread"


class GatewaySessionKey(BaseModel):
    """Uniquely identifies a conversation on a gateway platform.

    Composes platform + chat type + chat ID + optional thread ID into
    a composite key that can be used for session lookup and storage.
    """
    platform: str = Field(description="Platform identifier (telegram, discord, slack, etc.)")
    chat_type: str = Field(default="private", description="Type of chat: private, group, channel, thread")
    chat_id: str = Field(description="Platform-specific chat/conversation ID")
    thread_id: str | None = Field(default=None, description="Thread ID within the chat (if applicable)")

    @field_validator("platform")
    @classmethod
    def _validate_platform(cls, v: str) -> str:
        allowed = {p.value for p in GatewayPlatform}
        if v.lower() not in allowed:
            raise ValueError(f"Unknown platform: {v}. Allowed: {allowed}")
        return v.lower()

    @field_validator("chat_type")
    @classmethod
    def _validate_chat_type(cls, v: str) -> str:
        allowed = {c.value for c in GatewayChatType}
        if v.lower() not in allowed:
            raise ValueError(f"Unknown chat_type: {v}. Allowed: {allowed}")
        return v.lower()

    @field_validator("chat_id")
    @classmethod
    def _validate_chat_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("chat_id must not be empty")
        return v.strip()

    def composite_key(self) -> str:
        """Return a single string key for storage/indexing.

        Pattern: ``<platform>:<chat_type>:<chat_id>[:<thread_id>]``
        """
        parts = [self.platform, self.chat_type, self.chat_id]
        if self.thread_id:
            parts.append(self.thread_id)
        return ":".join(parts)

    @classmethod
    def from_composite_key(cls, key: str) -> "GatewaySessionKey":
        """Parse a composite key back into a session key object."""
        parts = key.split(":")
        if len(parts) < 3:
            raise ValueError(f"Invalid composite key: {key}")
        return cls(
            platform=parts[0],
            chat_type=parts[1],
            chat_id=parts[2],
            thread_id=parts[3] if len(parts) > 3 else None,
        )


class GatewaySession(BaseModel):
    """A gateway-persisted session that maps platform conversations to flow sessions.

    Created when a gateway receives a message and no existing session is found.
    Updated on every received message (last_activity_at).
    """
    key: GatewaySessionKey = Field(description="Composite key identifying the conversation")
    flow_session_id: str = Field(description="Weebot flow/session ID associated with this gateway session")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    title: str | None = Field(default=None, description="Conversation title (if available)")
    user_id: str | None = Field(default=None, description="Platform-specific user ID")
    is_active: bool = Field(default=True, description="Whether the session is active")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra platform-specific metadata")

    def touch(self) -> "GatewaySession":
        """Update last_activity_at to now."""
        return self.model_copy(update={"last_activity_at": datetime.now(timezone.utc)})

    def close(self) -> "GatewaySession":
        """Mark the session as inactive."""
        return self.model_copy(update={"is_active": False, "last_activity_at": datetime.now(timezone.utc)})

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if the session has expired based on TTL."""
        elapsed = (datetime.now(timezone.utc) - self.last_activity_at).total_seconds()
        return elapsed > ttl_seconds
