"""A27 (rate limit): RateLimitMiddleware sat inside the auth middleware, so rejected requests
never reached it, and its bucket was keyed by an unverified X-API-Key header. Guessing keys
was never throttled: each guess used a fresh header value, hence a fresh bucket."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient

from weebot.interfaces.web import rate_limit
from weebot.interfaces.web.rate_limit import RateLimitMiddleware


class _KeyGate(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("x-api-key") != "good":
            return JSONResponse({"detail": "bad key"}, status_code=401)
        return await call_next(request)


@pytest.fixture(autouse=True)
def _fresh_state():
    rate_limit._buckets.clear()
    rate_limit._auth_failures._buckets.clear()
    yield
    rate_limit._buckets.clear()
    rate_limit._auth_failures._buckets.clear()


def _app(limiter_outermost: bool = True) -> TestClient:
    app = FastAPI()

    @app.get("/api/sessions")
    async def sessions():
        return {"ok": True}

    if limiter_outermost:
        app.add_middleware(_KeyGate)
        app.add_middleware(RateLimitMiddleware, enabled=True)
    else:
        app.add_middleware(RateLimitMiddleware, enabled=True)
        app.add_middleware(_KeyGate)
    return TestClient(app)


def test_rotating_bad_keys_from_one_address_hit_429():
    client = _app()
    codes = [
        client.get("/api/sessions", headers={"X-API-Key": f"guess-{i}"}).status_code
        for i in range(30)
    ]
    assert codes[:10] == [401] * 10
    assert 429 in codes[10:]
    assert codes[-1] == 429


def test_the_failure_budget_is_per_address_and_blocks_even_a_good_key_until_the_window_passes():
    client = _app()
    for i in range(30):
        client.get("/api/sessions", headers={"X-API-Key": f"guess-{i}"})
    # Same test address, but a later valid request still gets the limiter's answer, not 401:
    # the failure budget is spent, so it is refused until the window passes.
    assert client.get("/api/sessions", headers={"X-API-Key": "good"}).status_code == 429


def test_successful_requests_never_spend_the_failure_budget():
    client = _app()
    for _ in range(15):
        assert client.get("/api/sessions", headers={"X-API-Key": "good"}).status_code == 200


def test_the_real_app_puts_the_limiter_outside_auth_and_the_body_limit_next():
    from weebot.interfaces.web.body_limit import BodyLimitMiddleware
    from weebot.interfaces.web.main import create_app

    classes = [m.cls for m in create_app().user_middleware]
    assert classes[0] is RateLimitMiddleware
    assert classes[1] is BodyLimitMiddleware
