"""Shared fixtures and mock adapters for weebot test suite."""

import os

# browser_use defaults ANONYMIZED_TELEMETRY to True and phones home to
# posthog (eu.i.posthog.com) on first use. That client leaves a connection
# open that blocks interpreter shutdown after the test session finishes —
# pytest prints its summary, then the process hangs until CI's job timeout
# kills it (surfaces as "cancelled", not "failed"). Must be set before any
# test module imports browser_use, so this runs at conftest import time.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_weebot_logger_level():
    """Un-pin the "weebot" logger's level before and after every test.

    ``StructuredLogger("weebot")`` (weebot/core/structured_logger.py) calls
    ``logging.getLogger("weebot").setLevel(logging.INFO)``. DI's
    ``configure_defaults()`` builds one of these lazily the first time any
    test resolves the ``"structured_logger"`` service. Loggers are global,
    process-wide singletons with no per-test cleanup, so once any test does
    that, "weebot" keeps an explicit INFO level for the rest of the session —
    and since Python resolves a logger's *effective* level by walking up to
    the nearest ancestor with an explicit level, every descendant logger
    (e.g. ``weebot.config.secret_accessor``) is silently capped at INFO too.
    A later test's own ``caplog.set_level(logging.DEBUG)`` only sets the
    root logger's level, so it can't override this — DEBUG records under
    ``weebot.*`` get dropped before they're even created, and caplog sees
    nothing (reproduced in isolation: constructing one ``StructuredLogger
    ("weebot")`` is enough to break every subsequent DEBUG-level
    ``weebot.*`` caplog assertion for the rest of the run).
    """
    logging.getLogger("weebot").setLevel(logging.NOTSET)
    yield
    logging.getLogger("weebot").setLevel(logging.NOTSET)


# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_dotenv_settings(monkeypatch):
    """Stop every settings class from reading the repo-root .env file.

    ``dotenv_settings`` is ranked above ``env_settings`` (settings.py:71-76),
    so a real ``.env`` on disk wins over both ``clean_env`` below and a test's
    own ``monkeypatch.setenv``. Without this, tests depend on the developer's
    local settings and can make live, billed calls.

    Patched on pydantic-settings' ``BaseSettings`` rather than on
    ``WeebotSettings.model_config``: a test that deletes
    ``weebot.config.settings`` from ``sys.modules`` gets a fresh class whose
    config points at ``.env`` again, but it still inherits this ``__init__``.
    ``_env_file`` is pydantic-settings' documented per-instance override;
    an explicit value passed by a test still wins.
    """
    from pydantic_settings import BaseSettings

    original_init = BaseSettings.__init__

    def _init_without_dotenv(self, *args, _env_file=None, **kwargs):
        original_init(self, *args, _env_file=_env_file, **kwargs)

    monkeypatch.setattr(BaseSettings, "__init__", _init_without_dotenv)


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """Give every test its own ``get_settings()`` instance.

    ``get_settings`` caches one ``WeebotSettings`` per process. Without a
    reset, the first test to call it fixes the values (and the env vars it
    saw) for every later test. Cleared before the test, after the ``.env``
    patch above, so the instance a test builds never read the real ``.env``;
    and cleared after, so it does not leak.
    """
    try:
        from weebot.config.settings import get_settings
    except Exception:
        yield
        return
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip real API keys from the environment for every test.

    Tests that need a key must set it explicitly via monkeypatch.
    """
    for var in (
        "KIMI_API_KEY",
        "DEEPSEEK_API_KEY",
        "XAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SLACK_WEBHOOK_URL",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def reset_connection_pool():
    """Reset module-level asyncio.Lock and pool registry before each test.

    The module-level _pool_lock must be re-created per test so it is bound
    to the current event loop. Without this, a lock created in one
    per-function event loop is reused in the next (closed) loop and deadlocks.

    Pools opened during the test MUST be closed (not just dropped from the
    registry) before the next test's reset. Each aiosqlite connection runs
    a non-daemon worker thread; clearing the registry without closing them
    orphans those threads, and Python's shutdown sequence blocks joining
    every non-daemon thread — with enough leaked pools across a full test
    run, the interpreter never exits and CI kills the job on timeout instead
    of a real pass/fail.
    """
    import asyncio
    import sys

    mod = sys.modules.get("weebot.infrastructure.persistence.connection_pool")
    if mod is not None:
        mod._pool_lock = None
        mod._pool_registry.clear()
    yield
    mod = sys.modules.get("weebot.infrastructure.persistence.connection_pool")
    if mod is not None:
        if mod._pool_registry:
            try:
                asyncio.run(mod.close_all_pools())
            except Exception:
                pass
        mod._pool_lock = None
        mod._pool_registry.clear()


@pytest.fixture(autouse=True)
def reset_settings_singletons():
    """Reset module-level _SETTINGS caches before each test.

    BashTool and PythonExecuteTool cache a WeebotSettings instance so that
    .env is only parsed once per process.  Tests that patch WeebotSettings
    need a clean slate each time so the mock takes effect.
    """
    import sys

    for mod_name in ("weebot.tools.bash_tool", "weebot.tools.python_tool"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            mod._SETTINGS = None
    yield
    # Reset again on teardown so later tests also start clean.
    for mod_name in ("weebot.tools.bash_tool", "weebot.tools.python_tool"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            mod._SETTINGS = None


@pytest.fixture(autouse=True)
def force_dense_embeddings_unavailable():
    """Force the local-embeddings singleton unavailable for every test.

    ``get_local_embeddings()`` (qmd_integration/embeddings.py:343-350) is the
    one chokepoint all six dense-leg call sites route through. The moment
    anything calls ``embed_query``/``embed_documents`` it lazily imports
    ``sentence_transformers`` -> torch (a >60s cold import that also
    downloads ~90MB uncached) -- a unit test has no business paying that.
    Pre-seed the singleton with an instance whose availability flags are
    forced False so ``is_available()`` reports "no dense leg" everywhere,
    without ever reaching ``_load_model``. Same reset-around-each-test
    convention as reset_connection_pool/reset_settings_singletons above.
    """
    import sys

    from weebot.qmd_integration.embeddings import LocalEmbeddings

    mod = sys.modules.get("weebot.qmd_integration.embeddings")
    if mod is None:
        yield
        return
    forced = LocalEmbeddings()
    forced._llama_available = False
    forced._sentence_transformers_available = False
    mod._embeddings = forced
    yield
    mod._embeddings = None


@pytest.fixture
def with_openai_key(monkeypatch):
    """Provide a fake OpenAI key so settings validation passes."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")


@pytest.fixture
def with_all_keys(monkeypatch):
    """Provide all API keys (fake values) for multi-provider tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KIMI_API_KEY", "kimi-test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test-key")


# ---------------------------------------------------------------------------
# Temp filesystem helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    """Return a path to a temporary SQLite database file."""
    return tmp_path / "test_projects.db"


@pytest.fixture
def tmp_cache(tmp_path) -> Path:
    """Return a path to a temporary cache directory."""
    cache = tmp_path / "cache"
    cache.mkdir()
    return cache


@pytest.fixture
def workspace_path(tmp_path) -> Path:
    """Create a temporary workspace directory for file operations tests."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def workspace_editor(workspace_path, monkeypatch):
    """Configure StrReplaceEditorTool to use temporary workspace."""
    # Patch the settings module before importing the editor
    import weebot.config.settings as settings_module

    monkeypatch.setattr(settings_module, "WORKSPACE_ROOT", workspace_path)
    monkeypatch.setattr(settings_module, "REQUIRED_PATH_PREFIX", str(workspace_path))

    # Clear any cached imports
    import sys

    # Remove cached file_editor to force re-import with new settings
    if "weebot.tools.file_editor" in sys.modules:
        del sys.modules["weebot.tools.file_editor"]
    if "weebot.infrastructure.security.security_validators" in sys.modules:
        del sys.modules["weebot.infrastructure.security.security_validators"]

    return workspace_path


# ---------------------------------------------------------------------------
# Mock AI provider
# ---------------------------------------------------------------------------


class MockModelProvider:
    """Fake IModelProvider that returns predictable responses without API calls."""

    def __init__(self, response: str = "[mock response]"):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def generate(self, prompt: str, task_type: Any = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "task_type": task_type})
        return self.response

    def last_prompt(self) -> str | None:
        return self.calls[-1]["prompt"] if self.calls else None


@pytest.fixture
def mock_provider():
    return MockModelProvider()


# ---------------------------------------------------------------------------
# Mock LLM (for SafetyChecker / core.agent which use langchain ChatOpenAI)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    """AsyncMock that simulates a LangChain LLM response."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=MagicMock(content='{"confirmation_required": "no", "plan_b": "no risk"}')
    )
    return llm


# ---------------------------------------------------------------------------
# Mock notifier
# ---------------------------------------------------------------------------


class MockNotifier:
    """Collects notifications instead of sending them."""

    def __init__(self):
        self.sent: list[dict[str, Any]] = []

    async def notify(self, notification: Any) -> None:
        self.sent.append(
            {
                "title": notification.title,
                "message": notification.message,
                "level": notification.level.value,
            }
        )

    async def notify_project_start(self, project_id: str, description: str) -> None:
        self.sent.append({"event": "start", "project_id": project_id})

    async def notify_completion(self, project_id: str, message: str) -> None:
        self.sent.append({"event": "complete", "project_id": project_id})

    async def notify_error(self, project_id: str, error: str, critical: bool = False) -> None:
        self.sent.append({"event": "error", "project_id": project_id, "error": error})

    async def notify_checkpoint(self, project_id: str, message: str) -> None:
        self.sent.append({"event": "checkpoint", "project_id": project_id})


@pytest.fixture
def mock_notifier():
    return MockNotifier()
