"""A10: public webhook routes buffered request bodies of any size before any check."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def _app(limit: int = 1024) -> TestClient:
    from weebot.interfaces.web.body_limit import BodyLimitMiddleware

    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=limit)

    @app.post("/echo")
    async def echo(request: Request):
        return {"n": len(await request.body())}

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return TestClient(app)


def test_a_small_body_passes():
    assert _app().post("/echo", content=b"x" * 100).json() == {"n": 100}


def test_a_declared_oversize_body_is_413_before_the_route_runs():
    r = _app().post("/echo", content=b"x" * 2048)
    assert r.status_code == 413


def test_a_chunked_oversize_body_is_413():
    def chunks():
        for _ in range(8):
            yield b"x" * 512

    r = _app().post("/echo", content=chunks())
    assert r.status_code == 413


def test_a_body_exactly_at_the_limit_passes():
    assert _app(1024).post("/echo", content=b"x" * 1024).status_code == 200


def test_get_requests_are_untouched():
    assert _app().get("/ping").json() == {"ok": True}


def test_the_real_app_has_the_limit_wired():
    from weebot.interfaces.web.body_limit import BodyLimitMiddleware
    from weebot.interfaces.web.main import create_app

    assert any(m.cls is BodyLimitMiddleware for m in create_app().user_middleware)
