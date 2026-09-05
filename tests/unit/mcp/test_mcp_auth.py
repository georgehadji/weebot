"""Unit tests for M12 MCP SSE authentication.

Three tests here previously asserted ``verify_token`` returned ``True`` /
``False``. That is not the ``TokenVerifier`` protocol, which requires
``AccessToken | None`` -- and ``BearerAuthBackend.authenticate`` reads
``.expires_at`` and ``.scopes`` off the result, so a bool made a **valid**
token raise ``AttributeError``. The tests did not merely miss the defect; they
asserted it as the contract, which is why it survived. They now assert the
protocol.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp.server.auth.provider import AccessToken

from weebot.config.secret_accessor import SecretAccessor
from weebot.mcp.server import _APIKeyTokenVerifier


class TestAPIKeyTokenVerifier:
    """Tests for the _APIKeyTokenVerifier helper."""

    async def test_verifier_accepts_correct_token(self) -> None:
        """A valid token yields an AccessToken, not True.

        BearerAuthBackend reads `.expires_at` and `.scopes` off this value.
        """
        verifier = _APIKeyTokenVerifier("secret")
        result = await verifier.verify_token("secret")
        assert isinstance(result, AccessToken)
        assert result.token == "secret"
        assert result.scopes == []
        assert result.expires_at is None

    async def test_verifier_rejects_wrong_token(self) -> None:
        """A bad token yields None -- the protocol's rejection value."""
        verifier = _APIKeyTokenVerifier("secret")
        assert await verifier.verify_token("wrong") is None

    async def test_verifier_uses_compare_digest(self) -> None:
        verifier = _APIKeyTokenVerifier("secret")
        with patch("hmac.compare_digest") as mock_compare:
            mock_compare.return_value = True
            result = await verifier.verify_token("secret")

        mock_compare.assert_called_once_with("secret", "secret")
        assert isinstance(result, AccessToken)


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
