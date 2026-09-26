"""OpenRouter implementation of ProviderAccountPort."""

from __future__ import annotations

import httpx

from weebot.application.ports.provider_account_port import ModelListing, ProviderAccountPort

_API = "https://openrouter.ai/api/v1"


class OpenRouterAccountAdapter(ProviderAccountPort):
    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    async def remaining_credits(self) -> int | None:
        # No key reads as zero credit, so OpenRouter-only models are skipped:
        # without a key every request to them would fail anyway.
        if not self._api_key:
            return 0
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{_API}/auth/key", headers={"Authorization": f"Bearer {self._api_key}"}
                )
            if resp.status_code != 200:
                return None
            return int(resp.json().get("data", {}).get("credits", 0))
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
