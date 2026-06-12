"""Apify platform HTTP adapter.

Wraps the Apify API v2 REST interface so any actor in the catalog can be
invoked as a weebot tool.  Requires APIFY_API_KEY in the environment.

Operations (pass as first arg to execute()):
  run_actor_sync       — blocking run, returns dataset items directly
  run_actor            — async run start, returns run_id + default_dataset_id
  get_run              — poll a run for status
  get_dataset_items    — fetch items from a completed dataset
  search_store         — search the Apify actor store
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re as _re
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

# Apify identifier format constraints (from Apify API documentation).
# actor_id: "{owner}/{name}" — both segments alphanumeric, dashes, underscores, dots.
_ACTOR_ID_RE = _re.compile(r'^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$')
# run_id and dataset_id: alphanumeric strings, 15–30 chars.
_RESOURCE_ID_RE = _re.compile(r'^[a-zA-Z0-9]{15,30}$')


def _validate_actor_id(actor_id: str) -> None:
    if not _ACTOR_ID_RE.match(actor_id):
        raise ValueError(f"Invalid actor_id format: {actor_id!r}")


def _validate_resource_id(rid: str, name: str) -> None:
    if not _RESOURCE_ID_RE.match(rid):
        raise ValueError(f"Invalid {name} format: {rid!r}")

from weebot.infrastructure.external_service_integration import (
    ExternalService,
    ServiceConfig,
    ServiceResponse,
    ServiceStatus,
    ServiceType,
)

logger = logging.getLogger(__name__)

_APIFY_BASE = "https://api.apify.com/v2"
# Synchronous runs block until the actor finishes — allow generous timeout.
_SYNC_TIMEOUT_SECS = 120
_DEFAULT_TIMEOUT_SECS = 30


class ApifyService(ExternalService):
    """Thin async wrapper around the Apify REST API v2."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        resolved_key = api_key or os.getenv("APIFY_API_KEY", "")
        config = ServiceConfig(
            name="apify",
            service_type=ServiceType.API,
            base_url=_APIFY_BASE,
            api_key=resolved_key,
            timeout=_SYNC_TIMEOUT_SECS,
            retry_attempts=2,
            enabled=bool(resolved_key),
        )
        super().__init__(config)
        self._sync_session: Optional[aiohttp.ClientSession] = None
        self._fast_session: Optional[aiohttp.ClientSession] = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._sync_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_SYNC_TIMEOUT_SECS),
            headers=self._auth_headers(),
        )
        self._fast_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT_SECS),
            headers=self._auth_headers(),
        )
        self._initialized = True

    async def shutdown(self) -> None:
        for sess in (self._sync_session, self._fast_session):
            if sess and not sess.closed:
                await sess.close()
        self._sync_session = None
        self._fast_session = None
        self._initialized = False

    async def health_check(self) -> ServiceStatus:
        if not self.config.api_key:
            return ServiceStatus.UNAVAILABLE
        resp = await self.execute("search_store", query="web scraper", limit=1)
        return ServiceStatus.HEALTHY if resp.success else ServiceStatus.UNAVAILABLE

    # ── dispatch ───────────────────────────────────────────────────────────

    async def execute(self, operation: str, **kwargs: Any) -> ServiceResponse:
        if not self.config.enabled:
            return ServiceResponse(success=False, error="APIFY_API_KEY not set", status_code=503)
        if not self._initialized:
            await self.initialize()

        handlers = {
            "run_actor_sync": self._run_actor_sync,
            "run_actor": self._run_actor,
            "get_run": self._get_run,
            "get_dataset_items": self._get_dataset_items,
            "search_store": self._search_store,
        }
        handler = handlers.get(operation)
        if handler is None:
            return ServiceResponse(success=False, error=f"Unknown operation: {operation}")
        try:
            return await handler(**kwargs)
        except ValueError as exc:
            return ServiceResponse(success=False, error=str(exc), status_code=400)

    # ── operations ─────────────────────────────────────────────────────────

    async def _run_actor_sync(
        self,
        actor_id: str,
        run_input: Optional[Dict[str, Any]] = None,
        memory_mbytes: int = 256,
    ) -> ServiceResponse:
        """POST to sync endpoint — blocks until actor finishes, returns items."""
        _validate_actor_id(actor_id)
        # Apify uses ~ instead of / in actor IDs for URL embedding
        url_id = actor_id.replace("/", "~")
        url = f"{_APIFY_BASE}/acts/{url_id}/runs/sync-get-dataset-items"
        params = {"memory": memory_mbytes}
        return await self._post(
            url, json_body=run_input or {}, params=params, session=self._sync_session
        )

    async def _run_actor(
        self,
        actor_id: str,
        run_input: Optional[Dict[str, Any]] = None,
        memory_mbytes: int = 256,
    ) -> ServiceResponse:
        """Start an async actor run; returns run metadata (run_id, dataset_id)."""
        _validate_actor_id(actor_id)
        url_id = actor_id.replace("/", "~")
        url = f"{_APIFY_BASE}/acts/{url_id}/runs"
        params = {"memory": memory_mbytes}
        return await self._post(
            url, json_body=run_input or {}, params=params, session=self._fast_session
        )

    async def _get_run(self, run_id: str) -> ServiceResponse:
        _validate_resource_id(run_id, "run_id")
        url = f"{_APIFY_BASE}/actor-runs/{run_id}"
        return await self._get(url, params=None, session=self._fast_session)

    async def _get_dataset_items(
        self, dataset_id: str, limit: int = 100
    ) -> ServiceResponse:
        _validate_resource_id(dataset_id, "dataset_id")
        url = f"{_APIFY_BASE}/datasets/{dataset_id}/items"
        return await self._get(url, params={"limit": limit}, session=self._fast_session)

    async def _search_store(
        self, query: str = "", limit: int = 20, category: Optional[str] = None
    ) -> ServiceResponse:
        url = f"{_APIFY_BASE}/store"
        params: Dict[str, Any] = {"limit": limit}
        if query:
            params["search"] = query
        if category:
            params["category"] = category
        return await self._get(url, params=params, session=self._fast_session)

    # ── HTTP helpers ───────────────────────────────────────────────────────

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}

    async def _get(
        self,
        url: str,
        params: Optional[Dict],
        session: Optional[aiohttp.ClientSession],
    ) -> ServiceResponse:
        return await self._request("GET", url, params=params, json_body=None, session=session)

    async def _post(
        self,
        url: str,
        json_body: Any,
        params: Optional[Dict],
        session: Optional[aiohttp.ClientSession],
    ) -> ServiceResponse:
        return await self._request("POST", url, params=params, json_body=json_body, session=session)

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict],
        json_body: Any,
        session: Optional[aiohttp.ClientSession],
    ) -> ServiceResponse:
        sess = session or self._fast_session
        start = datetime.now()
        for attempt in range(self.config.retry_attempts):
            try:
                async with sess.request(
                    method=method, url=url, params=params, json=json_body
                ) as resp:
                    elapsed = (datetime.now() - start).total_seconds() * 1000
                    text = await resp.text()
                    if resp.status in (200, 201):
                        try:
                            data = json.loads(text) if text else None
                        except json.JSONDecodeError:
                            data = {"raw": text}
                        return ServiceResponse(
                            success=True,
                            data=data,
                            status_code=resp.status,
                            execution_time_ms=elapsed,
                        )
                    # Non-2xx — never retry client errors (4xx)
                    err = f"HTTP {resp.status}: {text[:300]}"
                    is_client_error = 400 <= resp.status < 500
                    if attempt < self.config.retry_attempts - 1 and not is_client_error:
                        await asyncio.sleep(2**attempt)
                        continue
                    return ServiceResponse(
                        success=False,
                        error=err,
                        status_code=resp.status,
                        execution_time_ms=elapsed,
                    )
            except asyncio.TimeoutError:
                err = f"Timeout after {self.config.timeout}s"
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                return ServiceResponse(success=False, error=err)
            except Exception as exc:  # noqa: BLE001
                err = f"Request error: {exc}"
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                return ServiceResponse(success=False, error=err)
        return ServiceResponse(success=False, error="Unexpected retry exhaustion")
