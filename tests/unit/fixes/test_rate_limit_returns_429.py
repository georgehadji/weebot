"""A request over its rate limit gets a 429, and the refusal is audited.

Found by the dead-code audit: the 429 branch imported ``AuditLogger`` from
``audit_logger``, which defines ``SecurityAuditLogger`` and ``get_security_logger``
only, so every throttled request raised ImportError instead of being refused.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from weebot.infrastructure.security import audit_logger
from weebot.infrastructure.security.audit_logger import AuditEventType, SecurityAuditLogger
from weebot.interfaces.web import rate_limit
from weebot.interfaces.web.rate_limit import RateLimitMiddleware


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    rate_limit._buckets.clear()
    rate_limit._auth_failures._buckets.clear()
    log = SecurityAuditLogger(enable_anomaly_detection=False, enable_file_persistence=False)
    monkeypatch.setattr(audit_logger, "_logger", log)
    yield log
    rate_limit._buckets.clear()
    rate_limit._auth_failures._buckets.clear()


def test_a_request_over_the_limit_is_refused_and_audited(_fresh):
    app = FastAPI()

    @app.get("/api/sessions")
    async def sessions():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, enabled=True)
    client = TestClient(app, raise_server_exceptions=True)

    codes = [client.get("/api/sessions").status_code for _ in range(400)]
    assert 429 in codes

    refused = _fresh.get_events(event_type=AuditEventType.RATE_LIMIT_EXCEEDED)
    assert refused and refused[0].result == "denied"
