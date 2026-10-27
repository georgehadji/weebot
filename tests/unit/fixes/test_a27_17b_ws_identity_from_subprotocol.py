"""A27 (ownership half): a browser WebSocket carries its key in the subprotocol, never in an
X-API-Key header, so identity derivation saw "anonymous" and ownership checks failed."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import HTTPConnection

from weebot.interfaces.web import auth

KEY = "sekret-key-for-test"
OTHER = "another-key-for-test"


def _ws(headers=None, query: str = "") -> HTTPConnection:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return HTTPConnection({
        "type": "websocket", "headers": raw, "query_string": query.encode(),
        "client": ("203.0.113.9", 1), "path": "/ws/sessions/s1",
    })


def _http(headers=None) -> HTTPConnection:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return HTTPConnection({"type": "http", "headers": raw, "query_string": b"",
                           "client": ("203.0.113.9", 1), "path": "/api/x"})


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("WEEBOT_API_KEY", KEY)
    monkeypatch.delenv("WEEBOT_AUTH_MODE", raising=False)


def test_a_subprotocol_key_gives_the_same_principal_as_the_header():
    via_header = auth.get_current_user_id(_http({"X-API-Key": KEY}))
    via_socket = auth.get_current_user_id(
        _ws({"Sec-WebSocket-Protocol": f"weebot.v1, bearer.{KEY}"})
    )
    assert via_socket == via_header != "anonymous"


def test_the_query_token_gives_a_principal_on_a_socket_only():
    assert auth.get_current_user_id(_ws(query=f"token={KEY}")) != "anonymous"
    http_with_query = HTTPConnection({"type": "http", "headers": [], "client": ("1.1.1.1", 1),
                                      "query_string": f"token={KEY}".encode(), "path": "/"})
    assert auth.get_current_user_id(http_with_query) == "anonymous"


def test_a_wrong_subprotocol_key_stays_anonymous():
    wrong = _ws({"Sec-WebSocket-Protocol": f"bearer.{OTHER}"})
    assert auth.get_current_user_id(wrong) == "anonymous"


async def test_the_owner_may_open_the_session_socket_and_a_stranger_may_not():
    owner = auth.get_current_user_id(_http({"X-API-Key": KEY}))
    await auth.verify_session_ownership(
        _ws({"Sec-WebSocket-Protocol": f"weebot.v1, bearer.{KEY}"}), owner)
    with pytest.raises(HTTPException):
        await auth.verify_session_ownership(
            _ws({"Sec-WebSocket-Protocol": f"bearer.{OTHER}"}), owner)
