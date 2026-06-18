"""Unit-test isolation fixtures.

Unit tests must be hermetic. WeebotSettings loads the repo-root ``.env`` via
``env_file`` and also reads process environment variables, so a developer's
real ``.env`` (API keys, ``DAILY_AI_BUDGET``, ``BASH_TIMEOUT`` …) leaks into
settings-based unit tests and makes assertions environment-dependent.

The autouse fixture below points ``env_file`` at nothing and clears the
ambient config/provider variables so each unit test controls settings
explicitly via constructor kwargs or ``monkeypatch.setenv``.
"""
from __future__ import annotations

# Shared model constant used across vision/multimodal unit tests.
# Change here to update all callers at once.
VISION_TEST_MODEL = "claude-opus-4-8"

import pytest

# Config/provider env vars that may leak from the developer's shell or .env
# and perturb settings-based unit tests.
_AMBIENT_SETTINGS_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "KIMI_API_KEY",
    "DEEPSEEK_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "WEEBOT_API_KEY",
    "DAILY_AI_BUDGET",
    "BASH_TIMEOUT",
    "PYTHON_TIMEOUT",
    "SANDBOX_MAX_OUTPUT_BYTES",
    "SANDBOX_MODE",
    "SANDBOX_ALLOW_NETWORK",
)


@pytest.fixture(autouse=True)
def _isolate_weebot_settings(monkeypatch):
    """Stop the real .env and ambient env vars from polluting settings tests."""
    try:
        from weebot.config import settings as settings_module
    except Exception:
        # Settings module unavailable in this context — nothing to isolate.
        yield
        return

    # Disable .env loading for the duration of the test (auto-restored).
    new_config = dict(settings_module.WeebotSettings.model_config)
    new_config["env_file"] = None
    monkeypatch.setattr(settings_module.WeebotSettings, "model_config", new_config)

    # Clear ambient provider/config vars; individual tests opt back in via
    # monkeypatch.setenv or explicit constructor kwargs.
    for var in _AMBIENT_SETTINGS_VARS:
        monkeypatch.delenv(var, raising=False)

    yield

    # Reset mutable module-level state to prevent cross-test leakage
    # (architecture remediation Phase 2.3)
    try:
        from weebot.utils.rate_limiter import reset_all_buckets
        reset_all_buckets()
    except Exception:
        pass
    try:
        from weebot.infrastructure.event_bus import _reset_metrics_cache
        _reset_metrics_cache()
    except Exception:
        pass
    try:
        from weebot.application.services.metrics_bridge import reset_metrics_cache
        reset_metrics_cache()
    except Exception:
        pass
    # Browser pool is async — sync fixture can't await. Pool cleanup is
    # best-effort from fixtures; actual cleanup happens in browser tests.
    # The import serves as a smoke test that reset_global_pool exists.
    try:
        from weebot.infrastructure.browser.session_pool import reset_global_pool  # noqa: F401
    except Exception:
        pass
