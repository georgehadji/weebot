"""S6 / R18b (remaining-work plan 2026-10-29): the rate-limit bucket is the verified caller.

The limiter keyed its bucket by a hash of whatever ``X-API-Key`` the client sent, before
anyone checked it: a fresh junk key per request got a fresh bucket, and a caller using
``Authorization: Bearer`` fell to the shared IP bucket. The bucket is now the principal
``authenticate`` verified (cached on the request, so auth still runs once), else the IP.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from weebot.interfaces.web import auth
from weebot.interfaces.web.rate_limit import RateLimitMiddleware


def _request(**headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/sessions",
            "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()],
            "client": ("203.0.113.7", 5000),
        }
    )


@pytest.fixture
def verified(monkeypatch):
    keys = {"good-key": "alice"}

    async def _authenticate(conn, legacy_key=None):
        presented = conn.headers.get("x-api-key") or conn.headers.get("authorization", "")[7:]
        return keys.get(presented)

    monkeypatch.setattr(auth, "authenticate", _authenticate)


@pytest.mark.asyncio
async def test_junk_keys_share_the_ip_bucket(verified):
    first = await RateLimitMiddleware._resolve_principal(_request(x_api_key="junk-1"))
    second = await RateLimitMiddleware._resolve_principal(_request(x_api_key="junk-2"))
    assert first == second == "ip:203.0.113.7"


@pytest.mark.asyncio
async def test_a_bearer_caller_gets_its_own_bucket(verified):
    principal = await RateLimitMiddleware._resolve_principal(
        _request(authorization="Bearer good-key")
    )
    assert principal == "key:alice"


@pytest.mark.asyncio
async def test_an_anonymous_local_caller_uses_the_ip(monkeypatch):
    async def _anonymous(conn, legacy_key=None):
        return "anonymous"

    monkeypatch.setattr(auth, "authenticate", _anonymous)
    assert await RateLimitMiddleware._resolve_principal(_request()) == "ip:203.0.113.7"
