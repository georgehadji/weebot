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
