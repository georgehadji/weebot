# Weebot — Agent Instructions

This file is the single source of truth for AI coding assistants working on the **Weebot** repository. It describes the project type, layout, build/test commands, architecture rules, and development conventions. Treat everything below as the baseline before making changes.

---

## Project Overview

Weebot is a production-grade, autonomous AI agent framework written primarily in **Python**. It exposes a Clean Architecture core with multiple interfaces:

- **CLI** (`cli/main.py` and `weebot/interfaces/cli/`)
- **Web API / WebSocket** (`weebot/interfaces/web/main.py`, FastAPI)
- **MCP server** (`run_mcp.py`, `weebot/mcp/`)
- **Chat / messaging gateways** (Discord, Slack, Telegram adapters in `weebot/interfaces/gateways/`)
- **Next.js web UI** (`weebot-ui/`)

The framework runs an agentic loop (Plan → Critique → Pre-mortem → Execute → Review → Verify → Summarize) backed by LLM adapters, a CQRS event pipeline, sandboxed code execution, tool orchestration, and built-in skills.

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ (CI and documented runtime); source is linted against Python 3.10 syntax |
| Web framework | FastAPI + Uvicorn |
| UI | Next.js 14 + React 18 + TypeScript + Tailwind CSS (`weebot-ui/`) |
| AI/LLM | LangChain, OpenAI SDK, OpenRouter/direct-provider adapters, custom model cascade |
| Data validation | Pydantic v2, Pydantic Settings |
| Persistence | SQLite (default), with PostgreSQL adapters scaffolded; Alembic for migrations |
| Browser automation | Playwright, `browser-use` |
| CLI / UX | Click, Rich, Prompt Toolkit |
| Observability | Structlog, Prometheus, OpenTelemetry (optional no-op) |
| Messaging | Discord, Slack, Telegram adapters; SSE/WebSocket event broadcasting |
| Testing | pytest, pytest-asyncio, pytest-cov, pytest-mock |
| Linting / architecture | Ruff, Bandit, import-linter |

The root `package.json` only contains optional `@openrouter/*` Node.js SDK dependencies; it is **not** the primary package manifest. The UI has its own manifest in `weebot-ui/package.json`.

---

## Repository Layout

```
.
├── weebot/                     # Main Python package
│   ├── domain/                 # Pure business entities, Pydantic models, protocol ports
│   │   ├── models/             # Plan, Session, Event, CodeReview, IdeaContract, etc.
│   │   ├── ports.py            # Protocol ports (IModelProvider, IRepository, INotifier, ITool, EventPublisher)
│   │   ├── services/           # Domain services (session_memory, working_memory, human_interaction)
│   │   └── exceptions.py       # WeebotError hierarchy
│   ├── application/            # Use cases, orchestration, ports, flows, agents, CQRS, DI
│   │   ├── di/                 # Dependency-injection container (Container + mixins)
│   │   ├── ports/              # ABC port interfaces consumed by infrastructure
│   │   ├── flows/              # PlanActFlow, ChatFlow, SkillOptFlow, HyperAgentFlow, state classes
│   │   ├── agents/             # Planner, Executor, Dreamer, Retention, Critic, etc.
│   │   ├── cqrs/               # Mediator, commands, queries, handlers, pipeline behaviors
│   │   ├── services/           # Application services (task runner, model selection, code review, etc.)
│   │   └── skills/             # Skill registry and format converters
│   ├── infrastructure/         # Adapters implementing application/domain ports
│   │   ├── adapters/llm/       # OpenRouter, OpenAI, Anthropic, DeepSeek, Moonshot, resilient adapters
│   │   ├── persistence/        # SQLite/PostgreSQL state repo, event store, tool repo, checkpoint store
│   │   ├── browser/            # Playwright adapter and session pool
│   │   ├── observability/      # Logging, metrics, health checks, tracing
│   │   ├── notifications/      # Telegram, Windows toast, SSE adapters
│   │   ├── events/             # Async event bus / broker
│   │   └── mcp/                # MCP client/toolkit adapters
│   ├── interfaces/             # Entry points (thin)
│   │   ├── web/                # FastAPI app, routers, WebSocket, SSE
│   │   ├── cli/                # AgentRunner, event logger, behavior commands
│   │   ├── gateways/           # Discord, Slack, Telegram
│   │   └── factories.py        # Flow construction helpers
│   ├── core/                   # Cross-cutting concerns: bash_guard, circuit_breaker, safety, model cascade
│   ├── tools/                  # Agent-callable tools (bash, python, browser, file_editor, image_gen, etc.)
│   ├── skills/builtin/         # Built-in skills as SKILL.md / manifest.json packages
│   ├── scheduling/             # Scheduler and cron-like jobs
│   ├── config/                 # Settings, model registry, prompts, constants
│   ├── templates/              # YAML-based workflow templates
│   └── mcp/                    # MCP server implementation (WeebotMCPServer)
│
├── cli/                        # Top-level Click CLI (`python -m cli.main ...`)
├── tests/                      # Test suite
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests
│   ├── e2e/                    # End-to-end tests
│   └── conftest.py             # Shared fixtures
├── weebot-ui/                  # Next.js frontend
├── research_modules/           # Reproducibility, data validation, literature helpers
├── integrations/               # Obsidian and Zotero integrations
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Ruff + Bandit + pytest options
├── pytest.ini                  # pytest configuration (points to weebot/tests — see note below)
├── alembic.ini                 # Alembic / SQLite migration config
├── .importlinter               # Architecture boundary enforcement
├── .coveragerc                 # Coverage thresholds and omissions
├── Makefile                    # Convenience targets
├── Dockerfile.api              # FastAPI backend image
├── Dockerfile.web              # Next.js standalone image
├── docker-compose.yml          # api + web services
├── run.py                      # Interactive / diagnostic entry point
├── run_mcp.py                  # MCP server entry point
└── .env.example                # Environment variable reference
```

### Note on dual pytest configuration

Both `pyproject.toml` and `pytest.ini` configure pytest. `pytest.ini` currently sets `testpaths = weebot/tests`, but the actual test tree is `tests/` at the repository root. Use explicit paths such as `pytest tests/ -v` to avoid path mismatches.

---

## Entry Points

| Command | File | Purpose |
|---------|------|---------|
| `python run.py --interactive` | `run.py` | Conversational HITL agent loop using PlanActFlow |
| `python run.py --diagnostic` | `run.py` | Smoke-test that core modules import cleanly |
| `python -m cli.main health` | `cli/main.py` | Component health check |
| `python -m cli.main doctor` | `cli/main.py` | Auto-repair / diagnostics |
| `python -m cli.main flow run "task"` | `cli/main.py` | Run a PlanActFlow task |
| `python -m cli.main flow list` | `cli/main.py` | List sessions |
| `python -m cli.main flow resume <id> "input"` | `cli/main.py` | Resume a paused session |
| `python -m cli.main dream scan` | `cli/main.py` | DreamerAgent + IdeaGate cycle |
| `python -m cli.main skills list` | `cli/main.py` | List installed skills |
| `python -m cli.main agents list` | `cli/main.py` | List personas |
| `python run_mcp.py` | `run_mcp.py` | Start the MCP server (stdio or SSE) |
| `python -m weebot.interfaces.web.main` | `weebot/interfaces/web/main.py` | Start FastAPI backend on port 8000 |
| `cd weebot-ui && npm run dev` | `weebot-ui/package.json` | Start Next.js frontend on port 3000 |

---

## Build & Run Commands

### Python backend

```bash
# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add at least one AI provider key (OPENROUTER_API_KEY, etc.)

# Verify
python -m cli.main health
python run.py --diagnostic

# Run a task
python -m cli.main flow run "Analyze the codebase for security issues"

# Interactive mode
python run.py --interactive
```

### Web UI

```bash
cd weebot-ui
npm install
npm run dev      # http://localhost:3000
```

### Makefile targets

```bash
make install      # pip install -r requirements.txt + import-linter
make test         # pytest tests/ -v --tb=short
make lint-imports # import-lints architecture contracts
make check-arch   # architecture fitness + event bridge + security + persistence tests
make check        # test + check-arch + lint-imports
```

---

## Testing Instructions

- **Run all tests:**
  ```bash
  pytest tests/ -v
  ```

- **Run unit tests with coverage (matches CI):**
  ```bash
  pytest tests/unit/ -v --tb=short --cov=weebot --cov-report=term --cov-fail-under=60
  ```

- **Run architecture gates:**
  ```bash
  pytest tests/unit/test_architecture_fitness.py -v
  make lint-imports
  ```

- **Run specific test categories:**
  ```bash
  pytest tests/unit/test_domain_models.py -v
  pytest tests/integration/ -v
  pytest tests/e2e/test_persistence.py -v
  ```

- **Markers available:** `unit`, `integration`, `slow`. Deselect slow tests with:
  ```bash
  pytest tests/ -v -m "not slow"
  ```

- **Async tests** use `asyncio_mode = auto`, so new async tests do not need `@pytest.mark.asyncio`.

- Coverage thresholds:
  - CI enforces **≥ 60%** overall on `tests/unit/`.
  - `.coveragerc` documents aspirational per-layer thresholds (domain 90, application 80, infrastructure 70, tools 65, interfaces 50) but those are not enforced by the config file itself.

---

## Code Style & Linting

- **Ruff** is configured in `pyproject.toml`:
  - Target Python version: 3.10 syntax (`target-version = "py310"`).
  - Line length: 100.
  - Selected rule sets: `E`, `W`, `F`, `B` (bugbear), `SIM` (simplify), `UP` (pyupgrade).
  - Ignored: `B006`, `SIM102`, `SIM108`, `UP007`.
  - `B110` (try-except-pass without logging) is enforced in production code; tests are allowed broad catches.
  - Excluded paths include `.venv`, `Output/`, `weebot/GitNexus-main/`, `scripts/`, `examples/`.

- **Bandit** is configured in `pyproject.toml`:
  - No skips.
  - Excludes `.venv`, `Output/`, `weebot/GitNexus-main/`.
  - `B110` is tested.

- **import-linter** enforces Clean Architecture boundaries in `.importlinter`:
  1. `domain-purity` — `weebot.domain` must not import outer layers.
  2. `tools-no-db` — `weebot.tools` must not access `sqlite3` directly (allowed exceptions are listed).
  3. `infra-no-app-services` — `weebot.infrastructure` must depend on ports, not application services/flows/agents/CQRS/DI.
  4. `interfaces-no-infra` — `weebot.interfaces` must not depend on infrastructure adapters directly (composition-root exceptions are listed).

- **General conventions observed in the codebase:**
  - Use `async`/`await` for I/O-bound and agent-orchestration code.
  - Type hints are required for new functions and classes.
  - Use Pydantic models for structured outputs and configuration.
  - CLI output uses the `rich` library for consistency.
  - Use `structlog` for logging; configure via `weebot.infrastructure.observability.logging_config`.
  - Read environment variables through `weebot.config.settings.WeebotSettings`, never from `os.environ` directly except at the outermost entry point.
  - Never commit secrets; `.env` is ignored by Git.

---

## Architecture Rules

The project follows **Clean Architecture (Hexagonal Ports & Adapters)** with a CQRS mediator and state-machine flows. Dependency direction is inward:

```
Interfaces → Application → Domain
                ↑
         Infrastructure
                ↑
              Core
```

| Layer | Path | Rule |
|-------|------|------|
| Domain | `weebot/domain/` | Pure. No imports from application, infrastructure, interfaces, core, or tools. |
| Application | `weebot/application/` | Defines ports and orchestrates flows/agents/CQRS. No direct imports from infrastructure or interfaces (except `TYPE_CHECKING`). |
| Infrastructure | `weebot/infrastructure/` | Implements application/domain ports. No imports from `application.agents`, `.flows`, `.services`, `.cqrs`, `.di`. |
| Interfaces | `weebot/interfaces/`, `cli/` | Thin entry points. Wire the stack via the DI container. |
| Core | `weebot/core/` | Cross-cutting concerns (safety, circuit breaker, model cascade). Avoid importing application/infrastructure/interfaces. |

Boundaries are verified by:
- `tests/unit/test_architecture_fitness.py` — AST-based checks.
- `tests/unit/test_port_contracts.py` — port/adapter contract tests.
- `import-lints` via `.importlinter`.

When adding a new adapter, register it in `weebot.application.di` and ensure the import path does not violate the contracts above.

---

## Security Considerations

- **Command execution:** All shell commands must pass through `weebot/core/bash_guard.py` and `weebot/tools/bash_security.py`. The framework applies a multi-layer defense: regex pattern matching, behavioral analysis, entropy analysis, and semantic validation. Risk levels are SAFE, SUSPICIOUS, DANGEROUS, and BLOCKED.
- **Sandboxing:** Python code runs through the sandboxed execution path (`SandboxPort`) with timeout, output limit, and network gating.
- **Filesystem access:** `FilesystemPermission` declares allow/deny/interrupt rules for paths. Tools use the `BackendPort` abstraction rather than direct filesystem calls.
- **Approval policy:** `ExecApprovalPolicy` can be `DENY`, `ALWAYS_ASK`, or `AUTO_APPROVE`.
- **Secrets:** API keys live in `.env` only. `WeebotSettings` redacts credentials in exceptions. Never hardcode keys or log them.
- **Web security:** The FastAPI CORS configuration should list explicit origins. If you change it, do not use `"*"` together with `allow_credentials=True`.
- **MCP server:** SSE transport supports Bearer-token authentication via `WEEBOT_MCP_API_KEY`. Remote SSE binding requires `--allow-remote`.
- **Egress:** `weebot/core/egress_guard.py` monitors outbound requests.

---

## Deployment

The repository provides Docker assets for a two-service deployment:

- `Dockerfile.api` — Python 3.12 slim image running the FastAPI app with Uvicorn on port **8000**.
- `Dockerfile.web` — Node 20 Alpine multi-stage build of the Next.js standalone UI; the image exposes port **3000**.
- `docker-compose.yml` — defines `api` (port 8000) and `web` (port 80) services with a shared `workspace` volume.

Run:

```bash
docker compose up --build
```

For local development the backend and frontend are usually started separately (see Entry Points).

---

## Environment & Configuration

Copy `.env.example` to `.env` and configure at minimum one AI provider key. Important variables:

- `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `KIMI_API_KEY`, `XAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — at least one is required.
- `WEEBOT_WORKSPACE` — workspace root for file operations (default: current directory).
- `WEEBOT_SESSIONS_DB` — SQLite session DB path (default: `./weebot_sessions.db`).
- `WEEBOT_LOGS_DIR` — log output directory (default: `./logs`).
- `WEEBOT_MCP_API_KEY` — auth token for MCP SSE transport.
- `BASH_TIMEOUT`, `PYTHON_TIMEOUT`, `SANDBOX_MAX_OUTPUT_BYTES`, `SANDBOX_ALLOW_NETWORK` — sandbox limits.
- `DAILY_AI_BUDGET` — max daily AI spend in USD (default: 10.0).

Settings are loaded by `weebot.config.settings.WeebotSettings` using Pydantic Settings, with priority: constructor kwargs > `.env` > system environment.

---

## Development Conventions

- **Plan before large changes:** For non-trivial work (3+ steps or architectural changes), enter plan mode and update tests/docs accordingly.
- **Prefer the tool layer:** Do not execute shell commands directly. Use `weebot.tools.bash_tool` or `weebot.tools.powershell_tool` (preferred on Windows for complex scripts).
- **Use the DI container:** Resolve ports via `Container().configure_defaults()` rather than constructing adapters by hand.
- **Structured outputs:** Agents return Pydantic models. Add new output schemas in `weebot/domain/models/` or `weebot/models/structured_output.py` depending on the layer.
- **Tests for new functionality:** Add unit tests for domain/application changes and integration tests for new adapters or flows. Keep tests focused and deterministic.
- **Skills:** Built-in skills live in `weebot/skills/builtin/<skill>/` with a `SKILL.md` or `manifest.json`. Imported community skills are placed in `skills/import/`.
- **Documentation:** Update `AGENTS.md` when you add new entry points, change build/test commands, or modify architecture/security rules. Human-facing docs belong in `README.md` or the `docs/` directory.
- **Version control:** This project uses Git. See `.gitignore` for excluded files. Do not commit `.env`, SQLite databases, logs, or generated output under `Output/`.

---

## Where to Learn More

- `README.md` — high-level capabilities, CLI reference, and feature overview.
- `ARCHITECTURE.md` — detailed architecture map and recent changes.
- `CLAUDE.md` — Claude Code specific commands and workflow notes.
- `GEMINI.md` — additional project context and conventions.
- `docs/` — architecture decision records, setup guides, quality notes, and plans.
- `.github/workflows/architecture.yml` — CI pipeline definition.
