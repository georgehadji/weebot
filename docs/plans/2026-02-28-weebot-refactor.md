# weebot Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

## Progress Tracker

| Task | Status | Notes |
|------|--------|-------|
| **Phase 1** | | |
| Task 1: CLAUDE.md | ✅ Done | Created at root |
| Task 2: pyproject.toml | ✅ Done | Created at root |
| **Phase 2** | | |
| Task 3: Rename manus_win11/ → weebot/ | ⏳ Pending | Imports use manus_win11 in old flat files; new package files use manus_win11 path |
| Task 4: Replace Manus → weebot strings | ⏳ Pending | core/agent.py partially done (RecursiveWeebotAgent, system prompt) |
| **Phase 3** | | |
| Task 5: WeebotSettings (pydantic-settings) | ⏳ Pending | config/settings.py still uses raw constants |
| **Phase 4** | | |
| Task 6: domain/models.py | ⏳ Pending | |
| Task 7: domain/ports.py + exceptions.py | ⏳ Pending | |
| **Phase 5** | | |
| Task 8: tests/conftest.py + mock adapters | ⏳ Pending | tests/ dir doesn't exist yet |
| **Phase 6** | | |
| Task 9: Full verification | ⏳ Pending | Diagnostic passes ✅ (all 16 modules OK) |

## Completed Outside Plan
- ✅ Folder structure created (manus_win11/, research_modules/, integrations/, cli/)
- ✅ All source files copied to new package locations with corrected imports
- ✅ run.py + .env.example created
- ✅ docs/ + scripts/ + data/ folders populated
- ✅ LangChain 1.x compatibility fixes (AgentExecutor removed, ClassVar, langchain_core.prompts)
- ✅ aiohttp + langchain + langchain-openai installed
- ✅ Architecture design doc: docs/plans/2026-02-28-architecture-design.md
- ✅ .claude/launch.json created with 3 CLI configurations

**Goal:** Refactor the existing Manus-Win11 codebase into a clean, well-structured weebot package using Clean Architecture (Hexagonal / Ports & Adapters), replacing all "Manus" references with "weebot", adding pyproject.toml, pydantic-settings config, a tests/ directory, and a CLAUDE.md session guide.

**Architecture:** Clean/Hexagonal — domain layer (zero deps) → application layer (use cases, async) → adapters (AI providers, storage, notifications, tools). CLI and future Web UI call only the application layer. All external dependencies injected at startup.

**Tech Stack:** Python 3.11+, pydantic-settings, pytest + pytest-asyncio, ruff, mypy, click, rich, aiohttp, langchain

---

## Phase 1 — CLAUDE.md + pyproject.toml (No code changes, immediate value)

### Task 1: Write CLAUDE.md

**Files:**
- Create: `CLAUDE.md` (project root)

**Step 1: Create the file**

```markdown
# weebot — Claude Session Guide

## Project Overview
weebot is an AI Agent Framework for Windows 11. It runs autonomous tasks using
multi-model AI routing (Kimi, DeepSeek, Claude, GPT-4), persistent state (SQLite),
multi-channel notifications (Telegram, Slack), and research tools.

## Architecture: Clean / Hexagonal (Ports & Adapters)

```
[CLI]  [Web UI]  [Python API]
        ↓
[Application Layer: Use Cases]  ← weebot/application/
        ↓
[Domain: models, ports]         ← weebot/domain/
        ↓
[Adapters: AI, Storage, Tools]  ← weebot/adapters/
```

### Layer Rules (NEVER violate)
| Layer | Can import | Cannot import |
|-------|-----------|---------------|
| `weebot/domain/` | stdlib only | anything external |
| `weebot/application/` | `domain/`, stdlib, asyncio | `adapters/`, `cli/`, `web/` |
| `weebot/adapters/` | `domain/`, external libs | `application/` |
| `cli/` | `application/`, `domain/` | `adapters/` directly |

## Package Structure
```
weebot/
├── weebot/                  # Main package (not manus_win11)
│   ├── domain/              # models.py, ports.py, exceptions.py
│   ├── application/         # run_agent.py, manage_project.py, research.py
│   ├── adapters/
│   │   ├── ai/              # router.py, kimi.py, deepseek.py, claude.py, openai_adapter.py
│   │   ├── storage/         # sqlite_repo.py
│   │   ├── notifications/   # telegram.py, slack.py, log_notifier.py
│   │   ├── tools/           # powershell.py, browser.py
│   │   └── integrations/    # obsidian.py, zotero.py
│   ├── config/settings.py   # WeebotSettings(BaseSettings)
│   └── utils/logger.py
├── cli/main.py              # Click CLI
├── research_modules/        # reproducibility, data_validator, literature
├── integrations/            # obsidian, zotero
├── tests/                   # pytest suite
├── docs/plans/              # Architecture & feature design docs
├── scripts/                 # setup utilities
├── data/                    # source documents
├── run.py                   # --diagnostic / --interactive / --cli
├── pyproject.toml
└── .env                     # API keys (never commit)
```

## Naming Conventions
- Package name: `weebot` (import as `from weebot.domain.models import Task`)
- Classes: `WeebotAgent`, `WeebotConfig`, `WeebotSettings`
- Exceptions: `WeebotError` (base), `BudgetExceededError`, `SafetyError`
- CLI: `weebot create`, `weebot run`, `weebot status`
- No occurrences of "Manus" anywhere — always "weebot"

## Common Commands
```bash
# Run diagnostics
python run.py --diagnostic

# Run CLI
python run.py  # or: python -m cli.main

# Run tests
pytest tests/ -v

# Lint + format
ruff check . && ruff format .

# Type check
mypy weebot/
```

## Development Workflow for New Features
1. Write failing test in `tests/unit/` or `tests/integration/`
2. Run test to confirm it fails
3. Implement minimal code in appropriate layer
4. Run tests to confirm they pass
5. Run `ruff check .` and `mypy weebot/`
6. Commit with descriptive message

## Import Patterns
```python
# Domain (no deps)
from weebot.domain.models import Task, Project, AgentConfig
from weebot.domain.ports import IModelProvider, IRepository, INotifier

# Application (use cases)
from weebot.application.run_agent import RunAgentUseCase

# Adapters (never import from application)
from weebot.adapters.ai.router import ModelRouter
from weebot.adapters.storage.sqlite_repo import SQLiteRepository

# Config
from weebot.config.settings import WeebotSettings
```

## Key Design Decisions
- **Dependency Injection**: All adapters constructed at startup (run.py / CLI), never inside use cases
- **Async-first**: All I/O is async. Sync wrappers at boundary (CLI, Python API)
- **Safety**: Before any destructive PowerShell command, SafetyChecker asks LLM for "Plan B"
- **Cost tracking**: ModelRouter tracks daily spend; raises BudgetExceededError when over limit
- **Checkpoints**: Tasks can pause for human approval (human-in-the-loop)
- **Resume**: SQLite state allows picking up where we left off after crash/pause

## Environment Variables (.env)
```
KIMI_API_KEY=...
DEEPSEEK_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
SLACK_WEBHOOK_URL=...
DAILY_AI_BUDGET=10.0
```
At least one AI API key required. Startup validation raises clear error if none found.
```

**Step 2: Verify file was created**

Run: `python -c "open('CLAUDE.md').read(); print('CLAUDE.md OK')"`
Expected: `CLAUDE.md OK`

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md session guide for weebot"
```

---

### Task 2: Create pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Keep: `requirements.txt` (for reference only — can delete later)

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "weebot"
version = "0.1.0"
description = "AI Agent Framework for Windows 11"
readme = "docs/README.md"
requires-python = ">=3.11"
dependencies = [
    "langchain>=0.1.0",
    "langchain-openai>=0.0.5",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "python-dotenv>=1.0.0",
    "browser-use>=0.1.0",
    "playwright>=1.40.0",
    "numpy>=1.24.0",
    "pandas>=2.0.0",
    "aiohttp>=3.8.0",
    "requests>=2.31.0",
    "click>=8.0.0",
    "rich>=13.0.0",
    "pyyaml>=6.0",
    "openai>=1.0.0",
    "aiofiles>=23.0.0",
]

[project.optional-dependencies]
research = [
    "scipy>=1.10.0",
    "matplotlib>=3.7.0",
    "seaborn>=0.12.0",
    "pypandoc>=1.11",
    "python-docx>=0.8.11",
]
integrations = [
    "pyzotero>=1.5.0",
    "watchdog>=3.0.0",
]
windows = [
    "pywin32>=306",
    "wmi>=1.5.2",
]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.0.0",
    "ruff>=0.3.0",
    "mypy>=1.8.0",
]

[project.scripts]
weebot = "cli.main:cli"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.11"
strict = false
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Verify syntax**

Run: `python -c "import tomllib; tomllib.loads(open('pyproject.toml').read()); print('pyproject.toml OK')"`
Expected: `pyproject.toml OK`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pyproject.toml replacing requirements.txt"
```

---

## Phase 2 — Rename manus_win11 → weebot (Package Rename)

### Task 3: Rename package directory and update all imports

**Files:**
- Rename: `manus_win11/` → `weebot/`
- Modify: Every file that imports from `manus_win11`

**Step 1: Rename the directory**

```bash
mv manus_win11 weebot
```

**Step 2: Update all import references**

```bash
# Find all occurrences
grep -rn "manus_win11" weebot/ cli/ research_modules/ integrations/ run.py

# Replace in all Python files
find weebot/ cli/ research_modules/ integrations/ -name "*.py" -exec \
  sed -i 's/from manus_win11\./from weebot./g; s/import manus_win11/import weebot/g' {} +

# Also fix run.py
sed -i 's/manus_win11/weebot/g' run.py
```

**Step 3: Verify no manus_win11 references remain**

Run: `grep -rn "manus_win11" weebot/ cli/ run.py`
Expected: No output

**Step 4: Verify imports work**

Run: `python -c "from weebot.config.settings import *; print('Config OK')"`
Run: `python -c "from weebot.ai_router import ModelRouter; print('Router OK')"`
Expected: Both print OK

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename package manus_win11 → weebot"
```

---

### Task 4: Replace all "Manus" text with "weebot" (strings, comments, docstrings)

**Files:**
- Modify: All `.py` files in `weebot/`, `cli/`, `research_modules/`, `integrations/`
- Modify: `run.py`, `docs/*.md`

**Step 1: Find all Manus occurrences**

```bash
grep -rn "Manus\|manus" weebot/ cli/ research_modules/ integrations/ run.py docs/ \
  --include="*.py" --include="*.md" | grep -v ".pyc" | grep -v "manus_win11"
```

**Step 2: Replace in Python files**

```bash
# Replace class names: ManusAgent → WeebotAgent
find weebot/ cli/ -name "*.py" -exec \
  sed -i 's/ManusAgent/WeebotAgent/g; s/ManusConfig/WeebotConfig/g; s/Manus-Win11/weebot/g; s/Manus Win11/weebot/g; s/manus-win11/weebot/g' {} +

# Replace string references
find weebot/ cli/ research_modules/ integrations/ -name "*.py" -exec \
  sed -i 's/"Manus/"weebot/g; s/Manus agent/weebot agent/g; s/Manus Agent/weebot Agent/g' {} +
```

**Step 3: Verify class names**

```bash
grep -rn "ManusAgent\|ManusConfig" weebot/ cli/
```
Expected: No output (all renamed to WeebotAgent/WeebotConfig)

**Step 4: Update __init__.py to export WeebotAgent**

Edit `weebot/__init__.py`:
```python
"""weebot: AI Agent Framework for Windows 11."""
from weebot.agent_core_v2 import WeebotAgent, AgentConfig
from weebot.ai_router import ModelRouter, TaskType
from weebot.state_manager import StateManager, ProjectStatus
from weebot.notifications import NotificationManager

__all__ = [
    "WeebotAgent", "AgentConfig",
    "ModelRouter", "TaskType",
    "StateManager", "ProjectStatus",
    "NotificationManager",
]
```

**Step 5: Verify package imports**

Run: `python -c "from weebot import WeebotAgent; print('WeebotAgent OK')"`
Expected: `WeebotAgent OK`

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename Manus → weebot in all class names and strings"
```

---

## Phase 3 — Config Layer (pydantic-settings)

### Task 5: Create WeebotSettings with pydantic-settings

**Files:**
- Modify: `weebot/config/settings.py`
- Create: `tests/unit/test_settings.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_settings.py
import pytest
from unittest.mock import patch


def test_settings_loads_from_env():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "DAILY_AI_BUDGET": "5.0"}):
        from weebot.config.settings import WeebotSettings
        s = WeebotSettings()
        assert s.openai_api_key == "test-key"
        assert s.daily_budget == 5.0


def test_settings_no_keys_raises():
    with patch.dict("os.environ", {}, clear=True):
        from weebot.config.settings import WeebotSettings
        s = WeebotSettings()
        with pytest.raises(ValueError, match="at least one AI API key"):
            s.validate_at_least_one_key()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_settings.py -v`
Expected: FAIL (WeebotSettings doesn't exist yet)

**Step 3: Write implementation**

```python
# weebot/config/settings.py
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class WeebotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # AI providers
    kimi_api_key: str | None = None
    deepseek_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # Notifications
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    slack_webhook_url: str | None = None

    # Budget
    daily_ai_budget: float = 10.0

    # Paths
    workspace_root: Path = Path(r"C:\Users\Public\weebot_workspace")
    db_path: Path = Path("weebot.db")
    log_dir: Path = Path("logs")

    @property
    def daily_budget(self) -> float:
        return self.daily_ai_budget

    def validate_at_least_one_key(self) -> None:
        keys = [self.kimi_api_key, self.deepseek_api_key,
                self.anthropic_api_key, self.openai_api_key]
        if not any(keys):
            raise ValueError(
                "weebot requires at least one AI API key. "
                "Set KIMI_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY in .env"
            )

    def available_providers(self) -> list[str]:
        providers = []
        if self.kimi_api_key:
            providers.append("kimi")
        if self.deepseek_api_key:
            providers.append("deepseek")
        if self.anthropic_api_key:
            providers.append("claude")
        if self.openai_api_key:
            providers.append("openai")
        return providers
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_settings.py -v`
Expected: Both tests PASS

**Step 5: Update run.py diagnostic to use WeebotSettings**

In `run.py`, add after imports:
```python
def run_diagnostic():
    ...
    # Add at end of function:
    try:
        from weebot.config.settings import WeebotSettings
        s = WeebotSettings()
        s.validate_at_least_one_key()
        print(f"  [OK]  API keys: {s.available_providers()}")
    except ValueError as e:
        print(f"  [WARN] {e}")
```

**Step 6: Commit**

```bash
git add weebot/config/settings.py tests/unit/test_settings.py run.py
git commit -m "feat: add WeebotSettings with pydantic-settings and startup validation"
```

---

## Phase 4 — Domain Layer (Clean Architecture core)

### Task 6: Create domain/models.py

**Files:**
- Create: `weebot/domain/models.py`
- Create: `tests/unit/test_domain_models.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_domain_models.py
from weebot.domain.models import Task, Project, TaskStatus, ProjectStatus


def test_task_creation():
    task = Task(name="analyze", description="Analyze data", prompt="Analyze this dataset")
    assert task.name == "analyze"
    assert task.status == TaskStatus.PENDING


def test_project_add_task():
    project = Project(project_id="proj1", description="Test")
    task = Task(name="t1", description="d", prompt="p")
    project.add_task(task)
    assert len(project.tasks) == 1
    assert project.pending_count == 1


def test_project_completion():
    project = Project(project_id="proj1", description="Test")
    task = Task(name="t1", description="d", prompt="p")
    project.add_task(task)
    task.mark_complete("result")
    assert project.is_complete
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_domain_models.py -v`
Expected: ImportError

**Step 3: Implement models**

```python
# weebot/domain/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProjectStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    name: str
    description: str
    prompt: str
    task_type: str = "chat"
    system_prompt: str = ""
    depends_on: list[str] = field(default_factory=list)
    checkpoint: bool = False
    checkpoint_desc: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    use_cache: bool = True
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_complete(self, result: str) -> None:
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = datetime.now()

    def mark_failed(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()

    def mark_running(self) -> None:
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()


@dataclass
class Checkpoint:
    task_name: str
    description: str
    requires_input: bool = False
    input_prompt: str = ""
    resolved: bool = False
    resolution: str | None = None


@dataclass
class AgentConfig:
    project_id: str
    description: str
    auto_resume: bool = True
    daily_budget: float = 10.0
    max_retries: int = 3
    notification_channels: list[str] = field(default_factory=list)


@dataclass
class Project:
    project_id: str
    description: str
    status: ProjectStatus = ProjectStatus.PENDING
    tasks: list[Task] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    total_cost: float = 0.0

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.PENDING)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def is_complete(self) -> bool:
        return all(t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.FAILED)
                   for t in self.tasks)
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_domain_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add weebot/domain/models.py tests/unit/test_domain_models.py
git commit -m "feat: add domain models (Task, Project, Checkpoint, AgentConfig)"
```

---

### Task 7: Create domain/ports.py and domain/exceptions.py

**Files:**
- Create: `weebot/domain/ports.py`
- Create: `weebot/domain/exceptions.py`
- Create: `tests/unit/test_domain_ports.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_domain_ports.py
from weebot.domain.exceptions import WeebotError, BudgetExceededError, SafetyError
from weebot.domain.ports import IModelProvider, IRepository, INotifier


def test_budget_exceeded_is_weebot_error():
    exc = BudgetExceededError("Over limit")
    assert isinstance(exc, WeebotError)


def test_safety_error_is_weebot_error():
    exc = SafetyError("Dangerous operation")
    assert isinstance(exc, WeebotError)


def test_imodel_provider_is_protocol():
    from typing import runtime_checkable, Protocol
    assert issubclass(IModelProvider, Protocol)
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_domain_ports.py -v`
Expected: ImportError

**Step 3: Implement exceptions.py**

```python
# weebot/domain/exceptions.py
class WeebotError(Exception):
    """Base exception for all weebot errors."""


class BudgetExceededError(WeebotError):
    """Raised when daily AI budget is exceeded."""


class SafetyError(WeebotError):
    """Raised when a safety check fails for a critical operation."""


class TaskExecutionError(WeebotError):
    """Raised when a task fails after all retries."""


class ProjectNotFoundError(WeebotError):
    """Raised when a project ID is not found in the repository."""


class CheckpointError(WeebotError):
    """Raised for checkpoint-related failures."""
```

**Step 4: Implement ports.py**

```python
# weebot/domain/ports.py
from __future__ import annotations
from typing import Protocol, runtime_checkable, Any
from weebot.domain.models import Task, Project, AgentConfig


@runtime_checkable
class IModelProvider(Protocol):
    """Port for AI model providers (Kimi, DeepSeek, Claude, GPT)."""

    async def generate(
        self,
        prompt: str,
        task_type: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str: ...

    async def estimate_cost(self, prompt: str, task_type: str) -> float: ...


@runtime_checkable
class IRepository(Protocol):
    """Port for persistent project storage."""

    async def save_project(self, project: Project) -> None: ...
    async def load_project(self, project_id: str) -> Project: ...
    async def list_projects(self) -> list[dict[str, Any]]: ...
    async def delete_project(self, project_id: str) -> None: ...


@runtime_checkable
class INotifier(Protocol):
    """Port for multi-channel notifications."""

    async def notify(self, title: str, message: str, level: str = "info",
                     project_id: str | None = None) -> None: ...


@runtime_checkable
class ITool(Protocol):
    """Port for execution tools (PowerShell, Browser)."""

    @property
    def name(self) -> str: ...

    async def execute(self, command: str) -> dict[str, Any]: ...
```

**Step 5: Run tests**

Run: `pytest tests/unit/test_domain_ports.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add weebot/domain/ports.py weebot/domain/exceptions.py tests/unit/test_domain_ports.py
git commit -m "feat: add domain ports (IModelProvider, IRepository, INotifier, ITool) and exceptions"
```

---

## Phase 5 — Tests Infrastructure

### Task 8: Create conftest.py with mock adapters

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create conftest.py**

```python
# tests/conftest.py
import pytest
from weebot.domain.models import Task, Project, AgentConfig


class MockModelProvider:
    """Mock AI provider that returns deterministic responses."""

    def __init__(self, response: str = "mock response"):
        self.response = response
        self.calls: list[dict] = []

    async def generate(self, prompt: str, task_type: str, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "task_type": task_type})
        return self.response

    async def estimate_cost(self, prompt: str, task_type: str) -> float:
        return 0.001


class MockRepository:
    """In-memory project storage for tests."""

    def __init__(self):
        self._store: dict[str, Project] = {}

    async def save_project(self, project: Project) -> None:
        self._store[project.project_id] = project

    async def load_project(self, project_id: str) -> Project:
        if project_id not in self._store:
            from weebot.domain.exceptions import ProjectNotFoundError
            raise ProjectNotFoundError(project_id)
        return self._store[project_id]

    async def list_projects(self) -> list[dict]:
        return [{"project_id": p.project_id, "status": p.status.value}
                for p in self._store.values()]

    async def delete_project(self, project_id: str) -> None:
        self._store.pop(project_id, None)


class MockNotifier:
    """Captures notifications for assertion in tests."""

    def __init__(self):
        self.notifications: list[dict] = []

    async def notify(self, title: str, message: str, level: str = "info",
                     project_id: str | None = None) -> None:
        self.notifications.append({
            "title": title, "message": message,
            "level": level, "project_id": project_id,
        })


@pytest.fixture
def mock_provider():
    return MockModelProvider()


@pytest.fixture
def mock_repo():
    return MockRepository()


@pytest.fixture
def mock_notifier():
    return MockNotifier()


@pytest.fixture
def sample_task():
    return Task(name="test_task", description="A test task", prompt="Do something")


@pytest.fixture
def sample_project():
    return Project(project_id="test_proj", description="Test project")


@pytest.fixture
def agent_config():
    return AgentConfig(project_id="test_proj", description="Test", daily_budget=1.0)
```

**Step 2: Run existing tests with conftest**

Run: `pytest tests/ -v`
Expected: All existing tests still PASS, conftest fixtures available

**Step 3: Commit**

```bash
git add tests/conftest.py tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
git commit -m "test: add conftest.py with MockModelProvider, MockRepository, MockNotifier"
```

---

## Phase 6 — Verification & Diagnostic

### Task 9: Run full verification

**Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

**Step 2: Run ruff**

Run: `ruff check weebot/ cli/ tests/`
Expected: No errors (or fix any reported)

**Step 3: Run diagnostic**

Run: `python run.py --diagnostic`
Expected: All modules print OK

**Step 4: Verify no Manus references**

Run: `grep -rn "Manus\|manus_win11" weebot/ cli/ tests/ run.py CLAUDE.md`
Expected: No output

**Step 5: Final commit**

```bash
git add -A
git commit -m "refactor: complete weebot refactor — clean architecture, tests, CLAUDE.md"
```

---

## Summary of All Files Created/Modified

| Action | File |
|--------|------|
| Create | `CLAUDE.md` |
| Create | `pyproject.toml` |
| Rename | `manus_win11/` → `weebot/` |
| Modify | `weebot/__init__.py` |
| Modify | `weebot/config/settings.py` (pydantic-settings) |
| Create | `weebot/domain/__init__.py` |
| Create | `weebot/domain/models.py` |
| Create | `weebot/domain/ports.py` |
| Create | `weebot/domain/exceptions.py` |
| Create | `tests/__init__.py` |
| Create | `tests/unit/__init__.py` |
| Create | `tests/integration/__init__.py` |
| Create | `tests/conftest.py` |
| Create | `tests/unit/test_settings.py` |
| Create | `tests/unit/test_domain_models.py` |
| Create | `tests/unit/test_domain_ports.py` |
| Modify | `run.py` (use WeebotSettings) |
| Modify | All `weebot/**/*.py` (Manus→weebot rename) |
| Modify | All `cli/**/*.py` (Manus→weebot rename) |
