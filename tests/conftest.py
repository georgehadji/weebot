"""Shared fixtures and mock adapters for weebot test suite."""
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from typing import Any


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip real API keys from the environment for every test.

    Tests that need a key must set it explicitly via monkeypatch.
    """
    for var in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(var, raising=False)


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
    llm.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"confirmation_required": "no", "plan_b": "no risk"}'
    ))
    return llm


# ---------------------------------------------------------------------------
# Mock notifier
# ---------------------------------------------------------------------------

class MockNotifier:
    """Collects notifications instead of sending them."""

    def __init__(self):
        self.sent: list[dict[str, Any]] = []

    async def notify(self, notification: Any) -> None:
        self.sent.append({
            "title": notification.title,
            "message": notification.message,
            "level": notification.level.value,
        })

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
