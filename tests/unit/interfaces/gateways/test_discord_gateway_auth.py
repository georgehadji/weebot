"""Unit tests for Discord gateway allowlist enforcement (H5).

Covers:
- Allowlisted channels proceed to flow execution.
- Non-allowlisted channels receive a denial response.
- User-level allowlist narrowing blocks specific users.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_TEST_PUBLIC_KEY_HEX = "c12a20a80a7d4600647e751ec5ca00d639c3907dc595f9d619b773c407f5a4fe"


class TestDiscordGatewayAuth:
    """Validates allowlist enforcement in DiscordAdapter.process_interaction."""

    @pytest.fixture(autouse=True)
    def _mock_safety(self, mocker):
        """Mock SafetyChecker to avoid ChatOpenAI dependency."""
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

    @pytest.fixture
    def valid_payload(self):
        """A valid APPLICATION_COMMAND Discord interaction payload."""
        return {
            "type": 2,
            "data": {"name": "ask", "options": [{"name": "question", "value": "hello"}]},
            "channel_id": "123456",
            "guild_id": "789",
            "member": {"user": {"id": "user-42", "username": "TestUser"}},
            "token": "interaction-token",
            "id": "interaction-id",
        }

    @pytest.mark.asyncio
    async def test_allowlisted_channel_runs_flow(self, adapter, valid_payload):
        """Authorized channel calls build_tools, create_flow, and flow.run."""
        with patch.object(adapter, "is_authorized", return_value=True):
            with patch.object(adapter, "handle", return_value="/ask question: hello"):

                async def _fake_run():
                    yield MagicMock(type="message", message="Hello")

                mock_flow = MagicMock()
                mock_flow.run = MagicMock(side_effect=lambda _text: _fake_run())

                with (
                    patch(
                        "weebot.interfaces.factories.build_tools", return_value=AsyncMock()
                    ) as mock_build_tools,
                    patch(
                        "weebot.interfaces.factories.create_flow", return_value=mock_flow
                    ) as mock_create_flow,
                ):
                    result = await adapter.process_interaction(valid_payload)

        assert result["type"] == 4
        mock_build_tools.assert_called_once()
        mock_create_flow.assert_called_once()
        mock_flow.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_allowlisted_channel_denied(self, adapter, valid_payload):
        """Non-allowlisted channel receives denial and flow is never built."""
        with patch.object(adapter, "is_authorized", return_value=False):
            with (
                patch("weebot.interfaces.factories.build_tools") as mock_build_tools,
                patch("weebot.interfaces.factories.create_flow") as mock_create_flow,
            ):
                result = await adapter.process_interaction(valid_payload)

        assert result == {
            "type": 4,
            "data": {
                "content": (
                    "This channel isn't authorized to use this bot. "
                    "Ask an admin to add it to the allowlist."
                )
            },
        }
        mock_build_tools.assert_not_called()
        mock_create_flow.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_level_allowlist_narrowing(self, adapter):
        """A specific user blocked by user-level allowlist is denied."""
        payload = {
            "type": 2,
            "data": {"name": "ask", "options": []},
            "channel_id": "123456",
            "guild_id": "789",
            "member": {"user": {"id": "blocked-user", "username": "Blocked"}},
            "token": "tok",
            "id": "id",
        }

        def _auth_check(platform, chat_id, user_id):
            return user_id != "blocked-user"

        with patch.object(adapter, "is_authorized", side_effect=_auth_check):
            with (
                patch("weebot.interfaces.factories.build_tools") as mock_build_tools,
                patch("weebot.interfaces.factories.create_flow") as mock_create_flow,
            ):
                result = await adapter.process_interaction(payload)

        assert result["type"] == 4
        assert "isn't authorized" in result["data"]["content"]
        mock_build_tools.assert_not_called()
        mock_create_flow.assert_not_called()
