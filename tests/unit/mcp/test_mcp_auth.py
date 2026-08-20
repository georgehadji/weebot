"""Unit tests for M12 MCP SSE authentication."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from weebot.config.secret_accessor import SecretAccessor
from weebot.mcp.server import _APIKeyTokenVerifier


class TestAPIKeyTokenVerifier:
    """Tests for the _APIKeyTokenVerifier helper."""

    async def test_verifier_accepts_correct_token(self) -> None:
        verifier = _APIKeyTokenVerifier("secret")
        result = await verifier.verify_token("secret")
        assert result is True

    async def test_verifier_rejects_wrong_token(self) -> None:
        verifier = _APIKeyTokenVerifier("secret")
        result = await verifier.verify_token("wrong")
        assert result is False

    async def test_verifier_uses_compare_digest(self) -> None:
        verifier = _APIKeyTokenVerifier("secret")
        with patch("hmac.compare_digest") as mock_compare:
            mock_compare.return_value = True
            result = await verifier.verify_token("secret")

        mock_compare.assert_called_once_with("secret", "secret")
        assert result is True


class TestMCPSSECLI:
    """Tests for the MCP server CLI auth checks."""

    def test_cli_allow_remote_without_key_exits_2(self) -> None:
        """--allow-remote without WEEBOT_MCP_API_KEY exits with code 2."""
        from run_mcp import main

        SecretAccessor.set_source({})
        try:
            with (
                patch("weebot.config.settings.WeebotSettings.validate_at_least_one_key"),
                patch(
                    "sys.argv",
                    ["run_mcp.py", "--transport", "sse", "--host", "0.0.0.0", "--allow-remote"],
                ),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

            assert exc_info.value.code == 2
        finally:
            SecretAccessor.set_source(None)
