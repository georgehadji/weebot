# weebot Architecture Design
**Date:** 2026-02-28
**Status:** Approved
**Paradigm:** Clean Architecture (Hexagonal / Ports & Adapters)

---

## Context

weebot is an AI Agent Framework for Windows 11 that supports:
- CLI usage (primary)
- Python API (library import)
- Web dashboard (FastAPI, planned)

Primary goals: **scalability** and **maintainability**.
Platform: **Windows-first** (PowerShell sandbox), with cross-platform adapters where possible.

---

## Architecture Decision: Clean/Hexagonal

### Rationale
- Domain logic has zero external dependencies → trivially testable
- Each AI provider (Kimi, DeepSeek, Claude, GPT) is a swappable adapter
- CLI, Web UI, and Python API all call the same Application layer
- New tools (PowerShell, Browser, future: Terminal, SSH) are adapters
- SQLite can be replaced with PostgreSQL by swapping one adapter

### Layer Rules (enforced in code review)

| Layer | Can import | Cannot import |
|-------|-----------|---------------|
| `domain/` | stdlib only | anything external |
| `application/` | `domain/`, stdlib, `asyncio` | `adapters/`, `cli/`, `web/` |
| `adapters/` | `domain/`, external libs | `application/` |
| `cli/` | `application/`, `domain/` | `adapters/` directly |
| `web/` | `application/`, `domain/` | `adapters/` directly |

---

## Package Structure

```
weebot/
├── weebot/                          # Main Python package
│   ├── domain/
│   │   ├── models.py                # Task, Project, Checkpoint, AgentConfig
│   │   ├── ports.py                 # IModelProvider, IRepository, INotifier, ITool
│   │   └── exceptions.py            # WeebotError, BudgetExceededError, SafetyError
│   │
│   ├── application/
│   │   ├── run_agent.py             # RunAgentUseCase (async)
│   │   ├── manage_project.py        # CreateProject, ResumeProject, GetStatus, Delete
│   │   └── research.py             # InitExperiment, ValidateData, SyncObsidian
│   │
│   ├── adapters/
│   │   ├── ai/
│   │   │   ├── router.py            # ModelRouter: selects provider by TaskType + budget
│   │   │   ├── kimi.py              # KimiProvider implements IModelProvider
│   │   │   ├── deepseek.py          # DeepSeekProvider
│   │   │   ├── claude.py            # ClaudeProvider
│   │   │   └── openai_adapter.py    # OpenAIProvider
│   │   ├── storage/
│   │   │   └── sqlite_repo.py       # SQLiteRepository implements IRepository
│   │   ├── notifications/
│   │   │   ├── telegram.py          # TelegramNotifier implements INotifier
│   │   │   ├── slack.py             # SlackNotifier
│   │   │   └── log_notifier.py      # LogNotifier
│   │   ├── tools/
│   │   │   ├── powershell.py        # PowerShellTool implements ITool
│   │   │   └── browser.py           # BrowserTool implements ITool
│   │   └── integrations/
│   │       ├── obsidian.py
│   │       └── zotero.py
│   │
│   ├── config/
│   │   └── settings.py              # WeebotSettings(BaseSettings) via pydantic-settings
│   └── utils/
│       └── logger.py
│
├── cli/                             # Click CLI — calls application layer only
│   ├── __init__.py
│   └── main.py
│
├── web/                             # FastAPI — future
│   └── __init__.py
│
├── research_modules/                # Research use cases (wrapped by application/research.py)
│   ├── reproducibility.py
│   ├── data_validator.py
│   └── literature.py
│
├── tests/
│   ├── unit/                        # Pure domain + application tests (no I/O)
│   ├── integration/                 # Adapter tests
│   └── conftest.py                  # Fixtures, mock adapters
│
├── docs/plans/
├── scripts/
├── data/
├── run.py                           # Entry point: --diagnostic / --interactive / --cli
├── pyproject.toml                   # Replaces requirements.txt
└── CLAUDE.md                        # Session instructions
```

---

## Key Design Patterns

### Dependency Injection
All adapters are injected at startup — never constructed inside use cases:
```python
# In run.py / CLI startup:
settings = WeebotSettings()
repo = SQLiteRepository(settings.db_path)
notifier = CompositeNotifier([TelegramNotifier(settings), LogNotifier()])
provider = ModelRouter(settings)
use_case = RunAgentUseCase(repo=repo, notifier=notifier, provider=provider)
```

### Port Interfaces (domain/ports.py)
```python
class IModelProvider(Protocol):
    async def generate(self, prompt: str, task_type: TaskType, ...) -> str: ...

class IRepository(Protocol):
    async def save_project(self, project: Project) -> None: ...
    async def load_project(self, project_id: str) -> Project: ...

class INotifier(Protocol):
    async def notify(self, notification: Notification) -> None: ...

class ITool(Protocol):
    async def execute(self, command: str) -> ToolResult: ...
```

### Async-First
All use cases and adapters are async. Sync wrappers provided for Python API usage.

---

## Tooling

| Tool | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata + dependencies (replaces requirements.txt) |
| `pydantic-settings` | Typed config with `.env` loading + validation |
| `ruff` | Linting + formatting (replaces flake8 + black + isort) |
| `mypy` | Static type checking |
| `pytest` + `pytest-asyncio` | Async test suite |
| `pytest-cov` | Coverage reporting |

---

## Naming Conventions

- Package: `weebot` (not `manus_win11`)
- Classes: `WeebotAgent`, `WeebotConfig`, `WeebotSettings`
- Exceptions: `WeebotError` base, specific subclasses
- All CLI commands: `weebot create`, `weebot run`, `weebot status`
- No occurrences of "Manus" anywhere in codebase

---

## Testing Strategy

- **Unit tests** (`tests/unit/`): domain models, port contracts. Zero I/O.
- **Integration tests** (`tests/integration/`): adapters with real SQLite, mocked HTTP.
- **Mock adapters**: `MockModelProvider`, `MockRepository`, `MockNotifier` in `conftest.py`.
- Target coverage: ≥80% on domain + application layers.
