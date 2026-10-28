"""A client over its rate limit is audited once per throttled spell, not per request.

Found by review of the 429 fix: every refused request ran the security audit logger
(lock, hash chain, list copy, anomaly checks) on the event loop, so a request flood,
the case the limiter exists for, paid that cost on every rejection.
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
    rate_limit._throttled.clear()
    log = SecurityAuditLogger(enable_anomaly_detection=False, enable_file_persistence=False)
    monkeypatch.setattr(audit_logger, "_logger", log)
    yield log
    rate_limit._buckets.clear()
    rate_limit._auth_failures._buckets.clear()


def test_a_flood_is_one_audit_event(_fresh):
    app = FastAPI()

    @app.get("/api/sessions")
    async def sessions():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, enabled=True)
    client = TestClient(app)

    codes = [client.get("/api/sessions").status_code for _ in range(400)]
    assert codes.count(429) > 1
    assert len(_fresh.get_events(event_type=AuditEventType.RATE_LIMIT_EXCEEDED)) == 1
