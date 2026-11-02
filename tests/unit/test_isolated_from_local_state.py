"""Unit tests must not see the developer's .env or .weebot/ state (2026-10-31).

In a full run from a real checkout, three tests failed that passed in a clean copy:
- tests/integration/conftest.py copied the whole repo .env into os.environ at
  pytest_configure, and test_real_api_openrouter.py did it again at import, for every run
  that collected the integration folder. tests/conftest.py strips only nine known keys, so
  WEEBOT_FREE_ROLES, GROQ_API_KEY and the rest leaked into unit tests.
The .env load now happens only for live runs (WEEBOT_TEST_LIVE=1). The role overrides file
(.weebot/role_models.json) was already redirected by tests/unit/conftest.py; the last test
keeps it that way.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _integration_conftest():
    spec = importlib.util.spec_from_file_location(
        "_integration_conftest", ROOT / "tests" / "integration" / "conftest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_integration_conftest_loads_dotenv_only_for_live_runs(monkeypatch):
    mod = _integration_conftest()
    loaded = []
    monkeypatch.setattr(mod, "load_env_file", loaded.append)
    monkeypatch.delenv("WEEBOT_TEST_LIVE", raising=False)
    mod.pytest_configure(None)
    assert loaded == []
    monkeypatch.setenv("WEEBOT_TEST_LIVE", "1")
    mod.pytest_configure(None)
    assert len(loaded) == 1


def test_no_test_module_loads_dotenv_at_import():
    src = (ROOT / "tests" / "integration" / "test_real_api_openrouter.py").read_text(
        encoding="utf-8"
    )
    assert "\n_load_dotenv()" not in src


def test_the_role_overrides_file_is_not_the_real_one():
    from weebot.config.role_overrides import overrides_path
    from weebot.config.settings import WORKSPACE_ROOT

    assert not overrides_path().resolve().is_relative_to(WORKSPACE_ROOT.resolve())
