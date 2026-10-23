"""`/health` llm_providers covers every provider settings can name.

`check_llm_ports` knew openai, claude, kimi and deepseek by an if/elif chain;
openrouter and xai -- both in `settings._PROVIDER_KEYS` -- fell to "unknown",
so a machine with an OpenRouter key always read "degraded" (seen on the
2026-10-23 smoke run: "Some LLM providers unavailable (1/3)").
"""

from __future__ import annotations

import pytest

from weebot.config.settings import _PROVIDER_KEYS
from weebot.infrastructure.observability.health_checks import HealthCheckService, HealthStatus


class _Settings:
    def __init__(self, providers):
        self._providers = providers

    def available_providers(self):
        return list(self._providers)


@pytest.mark.asyncio
async def test_every_settings_provider_is_checked(monkeypatch):
    providers = list(_PROVIDER_KEYS)
    monkeypatch.setattr(
        "weebot.config.settings.get_settings", lambda: _Settings(providers)
    )
    health = await HealthCheckService().check_llm_ports()
    assert health.metadata["provider_status"] == {p: "available" for p in providers}
    assert health.status is HealthStatus.HEALTHY
