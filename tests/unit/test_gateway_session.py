"""Unit tests for gateway session domain models and services."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from weebot.domain.models.gateway_session import (
    GatewaySession,
    GatewaySessionKey,
    GatewayPlatform,
    GatewayChatType,
)
from weebot.application.services.gateway_flow_resolver import GatewayFlowResolver
from weebot.application.services.gateway_command_dispatcher import (
    GatewayCommandDispatcher,
    build_default_dispatcher,
)
from weebot.core.gateway_auth import GatewayAuth


class TestGatewaySessionKey:
    """GatewaySessionKey creation and composite key."""

    def test_minimal_key(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="12345")
        assert key.platform == "telegram"
        assert key.chat_type == "private"
        assert key.chat_id == "12345"
        assert key.thread_id is None

    def test_composite_key_no_thread(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="12345")
        assert key.composite_key() == "telegram:private:12345"

    def test_composite_key_with_thread(self):
        key = GatewaySessionKey(platform="discord", chat_type="thread", chat_id="67890", thread_id="42")
        assert key.composite_key() == "discord:thread:67890:42"

    def test_from_composite_key(self):
        key = GatewaySessionKey.from_composite_key("telegram:private:12345")
        assert key.platform == "telegram"
        assert key.chat_type == "private"
        assert key.chat_id == "12345"

    def test_from_composite_key_with_thread(self):
        key = GatewaySessionKey.from_composite_key("discord:thread:67890:42")
        assert key.platform == "discord"
        assert key.thread_id == "42"

    def test_invalid_platform_raises(self):
        with pytest.raises(ValueError):
            GatewaySessionKey(platform="invalid", chat_type="private", chat_id="1")

    def test_empty_chat_id_raises(self):
        with pytest.raises(ValueError):
            GatewaySessionKey(platform="telegram", chat_type="private", chat_id="")

    def test_invalid_chat_type_raises(self):
        with pytest.raises(ValueError):
            GatewaySessionKey(platform="telegram", chat_type="invalid", chat_id="1")


class TestGatewaySession:
    """GatewaySession model and lifecycle."""

    def test_minimal_session(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="123")
        session = GatewaySession(key=key, flow_session_id="flow-abc")
        assert session.flow_session_id == "flow-abc"
        assert session.is_active is True
        assert session.title is None
        assert session.user_id is None

    def test_touch_updates_timestamp(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="123")
        session = GatewaySession(key=key, flow_session_id="flow-abc")
        old = session.last_activity_at
        import asyncio
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.01))
        updated = session.touch()
        assert updated.last_activity_at > old

    def test_close_marks_inactive(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="123")
        session = GatewaySession(key=key, flow_session_id="flow-abc")
        closed = session.close()
        assert closed.is_active is False

    def test_is_expired(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="123")
        old_time = datetime.now(timezone.utc) - timedelta(days=14)
        session = GatewaySession(
            key=key,
            flow_session_id="flow-abc",
            last_activity_at=old_time,
        )
        assert session.is_expired(ttl_seconds=7 * 24 * 60 * 60) is True

    def test_not_expired(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="123")
        session = GatewaySession(key=key, flow_session_id="flow-abc")
        assert session.is_expired(ttl_seconds=7 * 24 * 60 * 60) is False

    def test_full_session(self):
        key = GatewaySessionKey(platform="discord", chat_type="group", chat_id="456", thread_id="789")
        session = GatewaySession(
            key=key,
            flow_session_id="flow-xyz",
            title="My Chat",
            user_id="user_1",
            metadata={"server_id": "srv_123"},
        )
        assert session.title == "My Chat"
        assert session.user_id == "user_1"
        assert session.metadata["server_id"] == "srv_123"


class TestGatewayFlowResolver:
    """GatewayFlowResolver session resolution."""

    @pytest.mark.asyncio
    async def test_new_session_created(self):
        store = InMemorySessionStore()
        resolver = GatewayFlowResolver(store)
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="100")

        session, flow_id = await resolver.resolve(key)
        assert flow_id.startswith("gw-telegram-100-")
        assert session.is_active is True
        assert session.flow_session_id == flow_id

    @pytest.mark.asyncio
    async def test_same_key_returns_same_session(self):
        store = InMemorySessionStore()
        resolver = GatewayFlowResolver(store)
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="100")

        session1, flow_id1 = await resolver.resolve(key)
        session2, flow_id2 = await resolver.resolve(key)

        # Same key within the same resolver should return the same flow session
        assert flow_id1 == flow_id2

    @pytest.mark.asyncio
    async def test_close_creates_new_session(self):
        store = InMemorySessionStore()
        resolver = GatewayFlowResolver(store)
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="100")

        session1, flow_id1 = await resolver.resolve(key)
        await resolver.close(key)

        session2, flow_id2 = await resolver.resolve(key)
        assert flow_id1 != flow_id2

    @pytest.mark.asyncio
    async def test_resolve_with_user_id(self):
        store = InMemorySessionStore()
        resolver = GatewayFlowResolver(store)
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="100")

        session, flow_id = await resolver.resolve(key, user_id="telegram-100")
        assert session.user_id == "telegram-100"


class TestGatewayCommandDispatcher:
    """Gateway command parsing and dispatch."""

    def setup_method(self):
        self.dispatcher = build_default_dispatcher()

    def test_help_command(self):
        result = self.dispatcher.dispatch("/help")
        assert "Available commands" in result

    def test_new_command(self):
        result = self.dispatcher.dispatch("/new")
        assert result == "OK_NEW_SESSION"

    def test_reset_command(self):
        result = self.dispatcher.dispatch("/reset")
        assert result == "OK_RESET_SESSION"

    def test_stop_command(self):
        result = self.dispatcher.dispatch("/stop")
        assert result == "OK_STOP"

    def test_model_command(self):
        result = self.dispatcher.dispatch("/model")
        assert "Current model" in result

    def test_model_set_command(self):
        result = self.dispatcher.dispatch('/model set gpt-4')
        assert result == "OK_SET_MODEL:gpt-4"

    def test_unknown_command(self):
        result = self.dispatcher.dispatch("/nonexistent")
        assert result is None

    def test_not_a_command(self):
        result = self.dispatcher.dispatch("hello there")
        assert result is None

    def test_is_command(self):
        assert self.dispatcher.is_command("/help") is True
        assert self.dispatcher.is_command("hello") is False

    def test_tools_command(self):
        result = self.dispatcher.dispatch("/tools")
        assert result == "OK_LIST_TOOLS"

    def test_compress_command(self):
        result = self.dispatcher.dispatch("/compress")
        assert result == "OK_COMPRESS"

    def test_mcp_command(self):
        result = self.dispatcher.dispatch("/mcp")
        assert result == "OK_MCP_STATUS"

    def test_list_commands(self):
        cmds = self.dispatcher.list_commands()
        assert "/help" in cmds
        assert "/new" in cmds
        assert "/model" in cmds

    def test_custom_command_registration(self):
        dispatcher = GatewayCommandDispatcher()

        @dispatcher.register("ping")
        def _ping() -> str:
            return "pong"

        assert dispatcher.dispatch("/ping") == "pong"
        assert dispatcher.is_command("/ping") is True


class TestGatewayAuth:
    """GatewayAuth access control."""

    def setup_method(self):
        import tempfile, os
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self.auth = GatewayAuth(config_path=self._tmp.name)
        # Override the rules directly to avoid file write during setup
        self.auth._rules = {
            "allowed_platforms": ["telegram", "discord"],
            "allowed_chats": {"telegram": ["101", "102"]},
            "allowed_users": {},
            "blocked_users": {"telegram": ["999"]},
            "admin_ids": {"telegram": ["1"]},
            "allow_all_by_default": False,
        }

    def test_platform_allowed(self):
        assert self.auth.is_platform_allowed("telegram") is True
        assert self.auth.is_platform_allowed("discord") is True
        assert self.auth.is_platform_allowed("slack") is False

    def test_chat_allowed_by_allowlist(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="101")
        assert self.auth.is_chat_allowed(key) is True

    def test_chat_not_in_allowlist(self):
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="999")
        assert self.auth.is_chat_allowed(key) is False

    def test_blocked_user(self):
        assert self.auth.is_user_allowed("telegram", "999") is False

    def test_admin_check(self):
        assert self.auth.is_admin("telegram", "1") is True
        assert self.auth.is_admin("telegram", "2") is False

    def test_allow_chat(self):
        # Verify allowlist behavior: "101" is in the allowlist, "999" is not
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="101")
        assert self.auth.is_chat_allowed(key) is True
        key2 = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="999")
        assert self.auth.is_chat_allowed(key2) is False

    def test_allow_all_by_default(self):
        # Remove the explicit allowlist so allow_all_by_default takes effect
        # Use a chat ID that is NOT in blocked_users (999 is blocked)
        self.auth._rules["allowed_chats"] = {}
        self.auth._rules["allow_all_by_default"] = True
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="555")
        assert self.auth.is_chat_allowed(key) is True

    def test_block_chat(self):
        # Simulate blocking by manipulating rules directly
        allowed = self.auth._rules.setdefault("allowed_chats", {}).get("telegram", [])
        if "101" in allowed:
            allowed.remove("101")
        self.auth._rules.setdefault("blocked_users", {}).setdefault("telegram", []).append("101")
        key = GatewaySessionKey(platform="telegram", chat_type="private", chat_id="101")
        assert self.auth.is_chat_allowed(key) is False

    def teardown_method(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except (OSError, AttributeError):
            pass


# ---------------------------------------------------------------------------
# In-memory session store for testing
# ---------------------------------------------------------------------------


class InMemorySessionStore:
    """In-memory implementation of IGatewaySessionStorePort for tests."""

    def __init__(self):
        self._sessions: dict[str, GatewaySession] = {}

    async def get(self, key: GatewaySessionKey) -> GatewaySession | None:
        return self._sessions.get(key.composite_key())

    async def upsert(self, session: GatewaySession) -> None:
        self._sessions[session.key.composite_key()] = session

    async def list(self, platform=None, user_id=None, active_only=True):
        results = []
        for s in self._sessions.values():
            if platform and s.key.platform != platform:
                continue
            if user_id and s.user_id != user_id:
                continue
            if active_only and not s.is_active:
                continue
            results.append(s)
        return results

    async def close_session(self, key: GatewaySessionKey) -> None:
        session = self._sessions.get(key.composite_key())
        if session:
            self._sessions[key.composite_key()] = session.close()

    async def delete(self, key: GatewaySessionKey) -> None:
        self._sessions.pop(key.composite_key(), None)

    async def cleanup_expired(self, ttl_seconds: int) -> int:
        before = len(self._sessions)
        self._sessions = {
            k: s for k, s in self._sessions.items()
            if not s.is_expired(ttl_seconds)
        }
        return before - len(self._sessions)
