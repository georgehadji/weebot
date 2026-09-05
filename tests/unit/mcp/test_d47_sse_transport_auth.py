"""D47 — MCP SSE authentication, proven behaviourally.

Candidate D47 from Wave 6 (`tasks/audits/defect_hunt_w6_interfaces.md`), left
uninvestigated there, recorded as *"token_verifier=None when
WEEBOT_MCP_API_KEY unset ⇒ an unauthenticated SSE server"*.

Investigating it found the claim true and the situation worse than stated:
**there was no configuration in which MCP SSE authentication worked.** Without
a key the server was unauthenticated; *with* a key it raised at construction.
Six defects in one chain, each proven below.

These drive the real Starlette app through `TestClient`, so they assert what a
client actually receives rather than what the source looks like — the gap W6's
own R-1 flagged about its D45 proof tests.

**Do not GET /sse with a valid token in a test.** It opens a server-sent-event
stream that stays open, and the test hangs. POST /messages/ exercises the same
`RequireAuthMiddleware` and returns.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from mcp.server.auth.provider import AccessToken

from weebot.mcp.server import _LOOPBACK_HOSTS, WeebotMCPServer

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

_KEY = "secret-key"
_ORIGIN = "http://127.0.0.1:8765"


@pytest.fixture
def authed_client():
    """A TestClient over an API-key-protected SSE app.

    `base_url` must be a loopback origin: FastMCP auto-enables DNS-rebinding
    protection for loopback binds, and TestClient's default `http://testserver`
    Host is rejected by it before auth is ever reached.
    """
    server = WeebotMCPServer(api_key=_KEY, host="127.0.0.1", port=8765)
    with TestClient(server.mcp.sse_app(), base_url=_ORIGIN) as client:
        yield client


class TestAuthIsReachableAtAll:
    """D47-e — passing `token_verifier` without `auth` raised at construction."""

    def test_a_server_with_an_api_key_can_be_constructed(self):
        """This raised ValueError, so setting the key broke the server outright.

        FastMCP: "Cannot specify auth_server_provider or token_verifier without
        auth settings". The only configuration that started was the
        unauthenticated one, which made every guard demanding a key
        unsatisfiable.
        """
        server = WeebotMCPServer(api_key=_KEY, host="127.0.0.1", port=8765)
        assert server.mcp.settings.auth is not None
        assert server.mcp._token_verifier is not None

    def test_without_a_key_the_server_is_unauthenticated(self):
        """The other half of the original claim, recorded rather than changed.

        No key means no verifier and no auth settings. That is the documented
        local-only mode; `run_sse` is what stops it reaching the network.
        """
        server = WeebotMCPServer(host="127.0.0.1", port=8765)
        assert server.mcp.settings.auth is None
        assert server.mcp._token_verifier is None


class TestVerifierHonoursTheProtocol:
    """D47-f — `verify_token` returned bool; the protocol requires AccessToken."""

    async def test_a_valid_token_yields_an_access_token(self):
        from weebot.mcp.server import _APIKeyTokenVerifier

        result = await _APIKeyTokenVerifier(_KEY).verify_token(_KEY)
        assert isinstance(result, AccessToken)
        # BearerAuthBackend reads both of these off the result.
        assert result.expires_at is None
        assert result.scopes == []

    async def test_an_invalid_token_yields_none(self):
        from weebot.mcp.server import _APIKeyTokenVerifier

        assert await _APIKeyTokenVerifier(_KEY).verify_token("wrong") is None


class TestTheWireBehaviour:
    """What a client actually gets. The proof W6's R-1 asked for."""

    def test_no_credentials_are_rejected(self, authed_client):
        assert authed_client.post("/messages/", json={}).status_code == 401

    def test_a_wrong_token_is_rejected(self, authed_client):
        response = authed_client.post(
            "/messages/", json={}, headers={"Authorization": "Bearer wrong"}
        )
        assert response.status_code == 401

    def test_a_correct_token_passes_authentication(self, authed_client):
        """400, not 401: the request got past auth and failed on an empty body.

        Asserting "not 401" rather than a specific success code keeps this
        about authentication. Before the fix a valid token produced a 500 from
        `AttributeError: 'bool' object has no attribute 'expires_at'`, so the
        assertion below also pins that the happy path no longer errors.
        """
        response = authed_client.post(
            "/messages/", json={}, headers={"Authorization": f"Bearer {_KEY}"}
        )
        assert response.status_code != 401
        assert response.status_code < 500

    def test_rejection_advertises_bearer_auth(self, authed_client):
        response = authed_client.get("/sse")
        assert response.status_code == 401
        assert "bearer" in response.headers.get("www-authenticate", "").lower()


class TestBindGuard:
    """D47-c — the guard lived in the CLI, not where the socket is bound."""

    @staticmethod
    def _serve(server) -> AsyncMock:
        """Run `run_sse` with the actual bind stubbed out."""
        served = AsyncMock()
        with patch.object(type(server.mcp), "run_sse_async", served):
            asyncio.run(server.run_sse())
        return served

    def test_non_loopback_without_a_key_is_refused(self):
        """`WeebotMCPServer(host="0.0.0.0")` bypassed run_mcp.py's check entirely."""
        server = WeebotMCPServer(host="0.0.0.0", port=9999)  # noqa: S104
        with pytest.raises(RuntimeError, match="without authentication"):
            self._serve(server)

    def test_non_loopback_via_run_sse_argument_is_refused(self):
        server = WeebotMCPServer()
        with pytest.raises(RuntimeError, match="without authentication"):
            with patch.object(type(server.mcp), "run_sse_async", AsyncMock()):
                asyncio.run(server.run_sse(host="0.0.0.0", port=9999))  # noqa: S104

    def test_non_loopback_with_a_key_is_allowed(self):
        """The guard requires authentication; it is not a ban on remote binds."""
        server = WeebotMCPServer(host="0.0.0.0", port=9999, api_key=_KEY)  # noqa: S104
        assert self._serve(server).called

    @pytest.mark.parametrize("host", sorted(_LOOPBACK_HOSTS))
    def test_loopback_without_a_key_still_works(self, host):
        """No regression: local use has never needed a key and still does not."""
        server = WeebotMCPServer(host=host, port=8765)
        assert self._serve(server).called


class TestCallSiteAgreement:
    """D47-a / D47-b — run_mcp.py passed host/port that run_sse did not accept."""

    def test_run_sse_accepts_what_run_mcp_passes(self):
        """`run_sse(host=..., port=...)` raised TypeError before binding anything.

        Both SSE tests in test_run_mcp.py passed anyway: they mocked the server
        with a bare `AsyncMock`, which accepts any signature. `spec=` would not
        have helped either — it constrains which attributes exist, not how they
        are called. Only autospec binds the real signature, which those tests
        now use.
        """
        inspect.signature(WeebotMCPServer.run_sse).bind(None, host="127.0.0.1", port=8765)

    def test_host_and_port_reach_fastmcp(self):
        """`_build_server()` never forwarded them, so --host/--port did nothing."""
        server = WeebotMCPServer(api_key=_KEY)
        with patch.object(type(server.mcp), "run_sse_async", AsyncMock()):
            asyncio.run(server.run_sse(host="0.0.0.0", port=4242))  # noqa: S104
        assert server.mcp.settings.host == "0.0.0.0"  # noqa: S104
        assert server.mcp.settings.port == 4242
