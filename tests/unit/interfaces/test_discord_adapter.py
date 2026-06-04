"""Unit tests for Discord gateway adapter (Enhancement 3).

Covers:
- Ed25519 signature verification (valid, tampered, missing)
- Interaction parsing (PING, slash commands, unknown types)
- Interaction processing (PONG, command execution, safety block)
- Response sending (success, failure)
- Webhook router (initialization, auth failure)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# A known Ed25519 keypair for testing.
# Generated with: nacl.signing.SigningKey.generate()
# Auto-generated Ed25519 keypair for test signature verification.
# Generated with: nacl.signing.SigningKey.generate()
_TEST_PUBLIC_KEY_HEX = "c12a20a80a7d4600647e751ec5ca00d639c3907dc595f9d619b773c407f5a4fe"
_TEST_PRIVATE_KEY_HEX = "032c49960c1fa3a0382bae2f8ff61ad486532e7379f56fbe79972a3eac54233c"

# Stripped-down pynacl-less test: we mock nacl entirely since it's a
# system dependency that may not be installed in CI (yet).


class TestDiscordAdapter:
    """Validates DiscordAdapter core logic."""

    # ── fixtures ────────────────────────────────────────────────────

    @pytest.fixture(autouse=True)
    def _mock_safety(self, mocker):
        """Mock SafetyChecker to avoid ChatOpenAI dependency.

        Imports the gateway base module first so that ``mocker.patch.object``
        replaces the reference *after* the module is in ``sys.modules``.
        """
        import weebot.interfaces.gateways.base as gw_base
        mocker.patch.object(gw_base, "SafetyChecker")

    @pytest.fixture
    def adapter(self):
        from weebot.interfaces.gateways.discord import DiscordAdapter

        return DiscordAdapter(
            public_key=_TEST_PUBLIC_KEY_HEX,
            bot_token="fake-bot-token",
            application_id="123456789",
            state_repo=AsyncMock(),
            llm=MagicMock(),
        )

    # ── signature verification ──────────────────────────────────────

    def test_verify_valid_signature(self, adapter):
        """Valid signature returns True."""
        # Patch the adapter's verify method to simulate success
        adapter._verify_key.verify = MagicMock(return_value=None)
        fake_sig = "ab" * 64
        assert adapter.verify_signature(b'{"test":1}', fake_sig, "1700000000") is True

    def test_verify_tampered_signature(self, adapter):
        """Tampered body/signature returns False."""
        from nacl.exceptions import BadSignatureError

        adapter._verify_key.verify = MagicMock(
            side_effect=BadSignatureError("bad sig")
        )
        assert adapter.verify_signature(b'{"test":1}', "badbadbad", "1700000000") is False

    def test_verify_empty_components(self, adapter):
        """Empty signature or body returns False."""
        assert adapter.verify_signature(b"", "", "") is False

    # ── interaction parsing ─────────────────────────────────────────

    def test_parse_ping_returns_none(self, adapter):
        """Type 1 (PING) returns None — caller sends immediate PONG."""
        payload = {"type": 1}
        assert adapter.parse_interaction(payload) is None

    def test_parse_command_extracts_text(self, adapter):
        """Type 2 (APPLICATION_COMMAND) returns GatewayMessage with text."""
        payload = {
            "type": 2,
            "data": {
                "name": "ask",
                "options": [{"name": "question", "value": "Hello world"}],
            },
            "channel_id": "123",
            "guild_id": "456",
            "member": {"user": {"id": "789", "username": "TestUser"}},
            "token": "interaction-token",
            "id": "interaction-id",
        }
        msg = adapter.parse_interaction(payload)
        assert msg is not None
        assert msg.platform == "discord"
        assert msg.external_id == "123"
        assert msg.text == "/ask question: Hello world"
        assert msg.metadata["user_id"] == "789"
        assert msg.metadata["guild_id"] == "456"

    def test_parse_unknown_type_returns_none(self, adapter):
        """Unknown interaction type returns None."""
        payload = {"type": 99, "data": {}}
        assert adapter.parse_interaction(payload) is None

    def test_parse_command_with_subcommands(self, adapter):
        """Sub-command groups are flattened into the prompt."""
        payload = {
            "type": 2,
            "data": {
                "name": "deploy",
                "options": [
                    {
                        "name": "service",
                        "options": [{"name": "name", "value": "api"}],
                    }
                ],
            },
            "channel_id": "1",
            "member": {"user": {"id": "2", "username": "Dev"}},
            "token": "tok",
        }
        msg = adapter.parse_interaction(payload)
        assert msg is not None
        assert "name: api" in msg.text

    # ── interaction processing ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_ping_returns_pong(self, adapter):
        """Type 1 payload returns {\"type\": 1}."""
        result = await adapter.process_interaction({"type": 1})
        assert result == {"type": 1}

    @pytest.mark.asyncio
    async def test_process_invalid_type_returns_error_message(self, adapter):
        """Unparseable interaction returns an error response."""
        result = await adapter.process_interaction({"type": 99})
        assert result["type"] == 4
        assert "couldn't understand" in result["data"]["content"].lower()

    @pytest.mark.asyncio
    async def test_process_with_safety_block(self, adapter):
        """When handle() returns None, safety-block message is returned."""
        # SafetyChecker blocks the message
        with patch.object(adapter, "handle", return_value=None):
            payload = {
                "type": 2,
                "data": {"name": "ask", "options": []},
                "channel_id": "1",
                "member": {"user": {"id": "2"}},
                "token": "tok",
            }
            result = await adapter.process_interaction(payload)
            assert result["type"] == 4
            assert "blocked by safety" in result["data"]["content"].lower()

    # ── response sending ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_send_response_success(self, adapter):
        """Successful Discord REST API post returns True."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="OK")

        # async with calls __aenter__ on the session.post return value
        mock_session_post = AsyncMock()
        mock_session_post.__aenter__.return_value = mock_resp

        with patch("aiohttp.ClientSession.post", return_value=mock_session_post) as mock_post:
            response = MagicMock()
            response.success = True
            response.text = "Hello"
            response.external_id = "123"

            result = await adapter.send_response(response)
            assert result is True
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_response_failure(self, adapter):
        """Failed Discord REST API post returns False."""
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="Bad request")

        mock_session_post = AsyncMock()
        mock_session_post.__aenter__.return_value = mock_resp

        with patch("aiohttp.ClientSession.post", return_value=mock_session_post):
            response = MagicMock()
            response.success = True
            response.text = "Hello"
            response.external_id = "123"

            result = await adapter.send_response(response)
            assert result is False

    @pytest.mark.asyncio
    async def test_send_response_unsuccessful(self, adapter):
        """When response.success is False, returns False immediately."""
        response = MagicMock()
        response.success = False
        result = await adapter.send_response(response)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_response_truncates(self, adapter):
        """Messages over 2000 characters are truncated."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="OK")

        mock_session_post = AsyncMock()
        mock_session_post.__aenter__.return_value = mock_resp

        with patch("aiohttp.ClientSession.post", return_value=mock_session_post) as mock_post:
            response = MagicMock()
            response.success = True
            response.text = "x" * 5000
            response.external_id = "123"

            await adapter.send_response(response)
            # Check that the posted content was truncated to 2000
            call_kwargs = mock_post.call_args[1]
            assert len(call_kwargs["json"]["content"]) == 2000


class TestDiscordWebhookRouter:
    """Validates the FastAPI webhook router."""

    def test_router_prefix(self):
        """Router is mounted at the correct prefix."""
        from weebot.interfaces.web.routers.discord_webhook import router

        assert router.prefix == "/api/gateway/discord"

    def test_router_has_interactions_route(self):
        """Router has the POST /interactions route registered."""
        from weebot.interfaces.web.routers.discord_webhook import router

        routes = [r for r in router.routes if hasattr(r, "path")]
        interaction_routes = [r for r in routes if "interactions" in r.path]
        assert len(interaction_routes) == 1

        route = interaction_routes[0]
        methods = getattr(route, "methods", set())
        assert "POST" in methods


class TestDiscordAdapterLifecycle:
    """Validates start/stop lifecycle."""

    @pytest.fixture(autouse=True)
    def _mock_safety(self, mocker):
        """Mock SafetyChecker to avoid ChatOpenAI dependency."""
        import weebot.interfaces.gateways.base as gw_base
        mocker.patch.object(gw_base, "SafetyChecker")

    @pytest.fixture
    def adapter_fixture(self):
        from weebot.interfaces.gateways.discord import DiscordAdapter

        return DiscordAdapter(
            public_key=_TEST_PUBLIC_KEY_HEX,
            bot_token="fake-bot-token",
            application_id="123456789",
            state_repo=AsyncMock(),
            llm=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_start_stop(self, adapter_fixture):
        """start() and stop() log and don't raise."""
        await adapter_fixture.start()
        await adapter_fixture.stop()
        # No exception means success
