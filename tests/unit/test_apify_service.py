"""Unit tests for ApifyService."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.infrastructure.adapters.apify.apify_service import ApifyService
from weebot.infrastructure.external_service_integration import ServiceStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status: int, body: object) -> MagicMock:
    """Build a mock aiohttp response context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.text = AsyncMock(return_value=json.dumps(body))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def _make_session(response_mock: MagicMock) -> MagicMock:
    session = MagicMock()
    session.request = MagicMock(return_value=response_mock)
    session.closed = False
    session.close = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    svc = ApifyService(api_key="test-key")
    return svc



# ---------------------------------------------------------------------------
# Tests: initialization
# ---------------------------------------------------------------------------

class TestApifyServiceInit:
    def test_disabled_when_no_key(self):
        svc = ApifyService(api_key="")
        assert not svc.config.enabled

    def test_enabled_with_key(self):
        svc = ApifyService(api_key="apify_abc")
        assert svc.config.enabled

    @pytest.mark.asyncio
    async def test_initialize_creates_sessions(self, service):
        await service.initialize()
        assert service._sync_session is not None
        assert service._fast_session is not None
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, service):
        await service.initialize()
        sess1 = service._sync_session
        await service.initialize()
        assert service._sync_session is sess1  # same object
        await service.shutdown()


# ---------------------------------------------------------------------------
# Tests: execute dispatch
# ---------------------------------------------------------------------------

class TestApifyServiceExecute:
    @pytest.mark.asyncio
    async def test_disabled_returns_error(self):
        svc = ApifyService(api_key="")
        resp = await svc.execute("run_actor_sync", actor_id="apify/web-scraper")
        assert not resp.success
        assert "APIFY_API_KEY" in resp.error

    @pytest.mark.asyncio
    async def test_unknown_operation_returns_error(self, service):
        await service.initialize()
        resp = await service.execute("does_not_exist")
        assert not resp.success
        assert "Unknown operation" in resp.error
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_run_actor_sync_success(self, service):
        items = [{"title": "Weebot AI", "url": "https://example.com"}]
        mock_resp = _make_response(200, items)
        mock_session = _make_session(mock_resp)

        await service.initialize()
        service._sync_session = mock_session

        resp = await service.execute(
            "run_actor_sync",
            actor_id="apify/google-search-scraper",
            run_input={"queries": "weebot"},
        )

        assert resp.success
        assert resp.data == items
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_run_actor_sync_replaces_slash_in_id(self, service):
        """Actor IDs use ~ in URLs, not /."""
        captured_urls = []

        async def fake_request(method, url, **kwargs):
            captured_urls.append(url)
            return _make_response(200, [])

        await service.initialize()
        service._sync_session = MagicMock()
        service._sync_session.request = MagicMock(
            return_value=_make_response(200, [])
        )
        # Patch _request to capture URL
        original_request = service._request

        async def capturing_request(method, url, **kwargs):
            captured_urls.append(url)
            return await original_request(method, url, **kwargs)

        service._request = capturing_request  # type: ignore[method-assign]

        await service.execute(
            "run_actor_sync",
            actor_id="supreme_coder/youtube-transcript-scraper",
            run_input={},
        )
        assert any("supreme_coder~youtube-transcript-scraper" in u for u in captured_urls)
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_search_store_success(self, service):
        store_resp = {"items": [{"name": "web-scraper", "description": "Scrape websites"}]}
        mock_resp = _make_response(200, store_resp)
        mock_session = _make_session(mock_resp)

        await service.initialize()
        service._fast_session = mock_session

        resp = await service.execute("search_store", query="web scraper", limit=5)
        assert resp.success
        assert resp.data == store_resp
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_http_error_returns_failure(self, service):
        mock_resp = _make_response(401, {"error": "Unauthorized"})
        mock_session = _make_session(mock_resp)

        await service.initialize()
        service._fast_session = mock_session
        service._sync_session = mock_session

        resp = await service.execute(
            "run_actor_sync",
            actor_id="apify/web-scraper",
            run_input={},
        )
        assert not resp.success
        assert "401" in resp.error
        # 4xx must NOT be retried — exactly one attempt
        assert mock_session.request.call_count == 1
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_server_error_is_retried(self, service):
        """5xx responses should trigger the retry loop (call_count > 1)."""
        mock_resp = _make_response(503, {"error": "Service Unavailable"})
        mock_session = _make_session(mock_resp)

        await service.initialize()
        service._fast_session = mock_session
        service._sync_session = mock_session

        with patch("asyncio.sleep", new_callable=AsyncMock):
            resp = await service.execute(
                "run_actor_sync",
                actor_id="apify/web-scraper",
                run_input={},
            )
        assert not resp.success
        # retry_attempts=2 means one retry → 2 total calls
        assert mock_session.request.call_count == service.config.retry_attempts
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_get_dataset_items(self, service):
        items = [{"name": "Alice"}, {"name": "Bob"}]
        mock_resp = _make_response(200, items)
        mock_session = _make_session(mock_resp)

        await service.initialize()
        service._fast_session = mock_session

        resp = await service.execute("get_dataset_items", dataset_id="ds_abc123", limit=50)
        assert resp.success
        assert resp.data == items
        await service.shutdown()


# ---------------------------------------------------------------------------
# Tests: health check
# ---------------------------------------------------------------------------

class TestApifyServiceHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_when_store_search_succeeds(self, service):
        store_resp = {"items": [{"name": "web-scraper"}]}
        mock_resp = _make_response(200, store_resp)
        mock_session = _make_session(mock_resp)

        await service.initialize()
        service._fast_session = mock_session

        status = await service.health_check()
        assert status == ServiceStatus.HEALTHY
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_unavailable_when_no_api_key(self):
        svc = ApifyService(api_key="")
        status = await svc.health_check()
        assert status == ServiceStatus.UNAVAILABLE
