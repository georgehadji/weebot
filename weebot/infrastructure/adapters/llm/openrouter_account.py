"""OpenRouter implementation of ProviderAccountPort."""

from __future__ import annotations

import time

import httpx

from weebot.application.ports.provider_account_port import ModelListing, ProviderAccountPort
from weebot.config.api_endpoints import OPENROUTER_API_BASE

_API = OPENROUTER_API_BASE


class OpenRouterAccountAdapter(ProviderAccountPort):
    # The cascade asks before every LLM call; one answer serves this long.
    _TTL_S: float = 60.0

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key
        self._cached: tuple[float, float | None] | None = None  # (monotonic time, value)

    async def remaining_credits(self) -> float | None:
        # No key reads as zero credit, so OpenRouter-only models are skipped:
        # without a key every request to them would fail anyway.
        if not self._api_key:
            return 0
        now = time.monotonic()
        if self._cached is not None and now - self._cached[0] < self._TTL_S:
            return self._cached[1]
        value = await self._fetch_remaining()
        if value is not None:  # an unknown is retried next call, never cached
            self._cached = (now, value)
        return value

    async def _fetch_remaining(self) -> float | None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{_API}/auth/key", headers={"Authorization": f"Bearer {self._api_key}"}
                )
            if resp.status_code != 200:
                return None
            # USD left under the key's limit. /auth/key has no "credits" field;
            # reading one returned 0 on every call. A key without a limit has
            # limit_remaining None: unknown, not zero.
            remaining = resp.json().get("data", {}).get("limit_remaining")
            return None if remaining is None else float(remaining)
        except Exception:
            # None means "unknown", NOT "zero". Returning 0 here was described as
            # failing open but did the opposite: 0 >= threshold is false, so a
            # transient error reaching openrouter.ai silently stripped every
            # OpenRouter-only model from the cascade.
            return None

    async def list_models(self) -> list[ModelListing]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_API}/models")
            resp.raise_for_status()
            data = resp.json()
        return [
            ModelListing(
                id=m.get("id", ""),
                context_length=m.get("context_length", 0) or 0,
                supports_tools="tools" in (m.get("supported_parameters") or []),
            )
            for m in data.get("data", [])
        ]
