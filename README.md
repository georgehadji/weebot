# Weebot — Production-Grade Autonomous AI Agent Framework

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Code style](https://img.shields.io/badge/code%20style-ruff-000000)](https://docs.astral.sh/ruff/)
[![Architecture](https://img.shields.io/badge/architecture-Clean%20Hexagonal%20%7C%20CQRS%20%7C%20Middleware-8A2BE2)]()
[![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)](https://docs.pytest.org/)
[![Status](https://img.shields.io/badge/status-stable-brightgreen)]()

**Weebot** is a production-grade framework for building, deploying, and operating autonomous AI agents. It combines Clean Architecture, CQRS event sourcing, middleware-based orchestration, multi-model cost cascading, secure sandboxed execution, and self-evolving skills into a single integrated platform.

Use it through the CLI, as a FastAPI service, as an MCP server, or embedded in chat gateways (Discord, Slack, Telegram).

→ [Quick Start](#quick-start) · [Features](#features) · [Architecture](#architecture) · [CLI Reference](#cli-reference) · [Security](#security-model) · [Testing](#testing) · [Deployment](#deployment)

---

## Table of Contents

- [Why Weebot](#why-weebot)
- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [Architecture](#architecture)
- [Operational Flow](#operational-flow)
- [Built-in Skills](#built-in-skills)
- [Security Model](#security-model)
- [Testing](#testing)
- [Deployment](#deployment)
- [Development](#development)
- [License](#license)

---

## Why Weebot

| Concern | Typical DIY Stack | Weebot |
|---|---|---|
| **Architecture degradation** | No enforced boundaries | 19 CI architecture fitness tests enforce Clean Architecture + middleware contracts |
| **Runaway LLM costs** | Single model for all tasks | FREE → Budget → Premium cascade with circuit breakers, per-role model configs, and task-preset tiers |
| **No continuous improvement** | Static prompts | SkillOpt optimizer refines skills from execution trajectories |
| **Auditability** | Ad-hoc logging | CQRS event stream with SQLite audit trail, Parquet export, and OpenTelemetry traces |
| **Unsafe execution** | Raw subprocess calls | Four-layer command defense + declarative filesystem permissions + sandboxed execution |
| **No agent code review** | Manual human review | Per-step LLM code review with approve/revise/reject routing and evidence-based trust scoring |
| **Reactive agents only** | Wait for user input | DreamerAgent surfaces ideas from failures and audit signals; IdeaGate filters before execution |
| **Tool fragmentation** | Each tool invents its own I/O | BackendPort unifies filesystem and execution operations behind seven standard methods |

---

## Features

### Autonomous Agent Loop
Plan → Critique → Pre-mortem → Execute (parallel tools) → Review → Verify → Summarize. Every state is typed, every tool call is traced, and every failure triggers Tree-of-Thoughts revision.

### Middleware-Based Orchestration
Composable `Middleware` components handle tool dispatch, trajectory monitoring, step validation, and sub-agent dispatch through `before_request`, `after_response`, and `after_tool_call` lifecycle hooks.

### Multi-Model Cost Cascade
Per-role model configuration routes tasks through free, budget, and premium model tiers. Circuit breakers and daily budget limits prevent runaway spend.

### Per-Step Code Review
A dedicated Critic model reviews each execution step before the agent continues. Verdicts — `approve`, `revise`, or `reject` — feed into trust scoring and replanning.

### DreamerAgent + IdeaGate
Autonomous ideation surfaces `IdeaContract` proposals from failures, opportunities, and audit violations. Contracts pass through `IntentReview` (coherence/safety) and `MainReview` (risk scoring) before execution.

### TrustReport & Retention
Pure-computation `TrustReport` compares code-review verdicts against CoVe fact-checking to produce `clean`/`watch`/`investigate` bands. `RetentionAgent` recommends `keep`/`improve`/`park`/`prune` for completed sessions.

### Unified BackendPort
All filesystem and execution tools use one `BackendPort` abstraction: `ls`, `read`, `write`, `edit`, `glob`, `grep`, `execute`. `FilesystemPermission` gates path-level access declaratively.

### Declarative Task Presets
`simple`, `standard`, and `complex` presets control pre-mortem depth, step validation, critique thresholds, and max steps — injected at configuration time without changing flow logic.

### Secure Sandboxed Execution
Python and shell execution runs through `SandboxPort` with configurable timeouts, output limits, and network gating.

### Self-Evolving Skills
Built-in skills cover SEO optimization, architecture design, TDD development, web research, competitive analysis, reasoning, multi-LLM orchestration, and more. The SkillOpt optimizer iteratively improves skill manifests from real trajectories.

### Image Generation Cascade
Multi-provider image generation routes through Ideogram, Recraft, Flux.2 Pro, Sourceful Riverflow, and SVG template fallbacks for logos, icons, banners, and OG cards.

---

## Quick Start

### Prerequisites

- Python 3.12+
- At least one AI provider API key (OpenRouter recommended)
- (Optional) Node.js 20+ for the Next.js UI

### Installation

```bash
git clone https://github.com/georgehadji/weebot.git
cd weebot
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add at least one provider key:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

### Verify

```bash
python -m cli.main health
python run.py --diagnostic
```

### Run your first task

```bash
python -m cli.main flow run "Analyze the codebase for security issues"
```

### Interactive mode

```bash
python run.py --interactive
```

### Run with a skill

```bash
python run.py --interactive --skill seo_optimizer
```

---

## Configuration

Configuration is loaded from `.env` via Pydantic Settings. Key variables:

| Variable | Purpose | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | Unified access to 350+ models | — |
| `DEEPSEEK_API_KEY` | Direct DeepSeek access | — |
| `KIMI_API_KEY` | Direct Moonshot Kimi access | — |
| `ANTHROPIC_API_KEY` | Direct Anthropic Claude access | — |
| `OPENAI_API_KEY` | Direct OpenAI access | — |
| `WEEBOT_WORKSPACE` | Workspace root for file operations | Current directory |
| `WEEBOT_SESSIONS_DB` | SQLite session database | `./weebot_sessions.db` |
| `WEEBOT_LOGS_DIR` | Log output directory | `./logs` |
| `DAILY_AI_BUDGET` | Max daily AI spend in USD | `10.0` |
| `BASH_TIMEOUT` | Shell command timeout in seconds | `30` |
| `PYTHON_TIMEOUT` | Python sandbox timeout in seconds | `30` |
| `SANDBOX_ALLOW_NETWORK` | Allow sandboxed code network access | `false` |
| `WEEBOT_MCP_API_KEY` | Auth token for MCP SSE transport | — |

See `.env.example` for the full reference.

---

## Running from Slack / Telegram / WhatsApp / Signal / Email

Weebot's chat gateways run inside the FastAPI web server:

```bash
python -m weebot.interfaces.web.main
# or: uvicorn weebot.interfaces.web.main:app --host 0.0.0.0 --port 8000
```

**Telegram** — create a bot with [@BotFather](https://t.me/BotFather), then set
`TELEGRAM_BOT_TOKEN` in `.env`. The bot starts long-polling automatically
when the web server boots — no public URL required.

**Slack** — create a Slack app, enable the Events API, and subscribe to
`message.channels` and `app_mention`. Set the request URL to
`https://<your-host>/api/gateway/slack/events` (needs a public/tunnelled
host — e.g. `ngrok http 8000` for local testing). Set `SLACK_BOT_TOKEN`
(from OAuth & Permissions) and `SLACK_SIGNING_SECRET` (from Basic
Information) in `.env`.

**WhatsApp** — create a Meta app with the WhatsApp product enabled. Set the
webhook request URL to `https://<your-host>/api/gateway/whatsapp/webhook`
and a verify token of your choosing (`WHATSAPP_WEBHOOK_VERIFY_TOKEN`). Set
`WHATSAPP_BUSINESS_API_TOKEN` and `WHATSAPP_BUSINESS_PHONE_NUMBER_ID` in
`.env`; `WHATSAPP_APP_SECRET` is optional and enables signature
verification on incoming events.

**Signal** — run a [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)
instance linked to a phone number, then set `SIGNAL_CLI_REST_URL` and
`SIGNAL_ACCOUNT_NUMBER` in `.env`. Polls the REST API in the background —
no public URL required.

**Email** — set `EMAIL_IMAP_USER`/`EMAIL_IMAP_PASSWORD` (use an app
password for providers with 2FA, e.g. Gmail) plus the IMAP/SMTP server
settings in `.env`. Polls IMAP for unseen mail in the background; replies
are sent over SMTP. The adapter never auto-replies to its own address or
to senders that look automated (`no-reply`, `mailer-daemon`, etc.) to
avoid autoresponder loops.

**Access control** — inbound chats are denied by default. Allowlist a chat
before the bot will respond to it:

```bash
python -m cli.main gateway allowlist add --platform telegram --id <chat_id>
python -m cli.main gateway allowlist add --platform slack --id <channel_id>
python -m cli.main gateway allowlist add --platform whatsapp --id <phone_number>
python -m cli.main gateway allowlist add --platform signal --id <phone_number>
python -m cli.main gateway allowlist add --platform email --id <email_address>
python -m cli.main gateway allowlist list           # view current rules
python -m cli.main gateway sessions list             # active conversations
```

Set `WEEBOT_GATEWAY_AUTH_ENABLED=0` to disable the allowlist entirely
(only for a private, single-user deployment). See `.env.example` for the
full list of gateway environment variables.

---

## CLI Reference

### Flow orchestration

| Command | Description |
|---|---|
| `python -m cli.main flow run "task"` | Execute a PlanActFlow task |
| `python -m cli.main flow list` | List active and completed sessions |
| `python -m cli.main flow resume <id> "answer"` | Resume a paused session |
| `python -m cli.main flow cancel <id>` | Cancel a running session |
| `python -m cli.main flow export <id>` | Export session to JSONL |

### Dream pipeline

| Command | Description |
|---|---|
| `python -m cli.main dream scan` | Run DreamerAgent + IdeaGate cycle |
| `python -m cli.main dream list` | List pending idea contracts |
| `python -m cli.main dream build <id>` | Execute an approved contract |

### Skills & agents

| Command | Description |
|---|---|
| `python -m cli.main skills list` | List installed skills |
| `python -m cli.main flow skillopt <name>` | Optimize a skill from trajectories |
| `python -m cli.main agents list` | List available personas |
| `python -m cli.main agents route "task"` | Route a task to the best persona |

### Diagnostics & security

| Command | Description |
|---|---|
| `python -m cli.main health` | Component health check |
| `python -m cli.main doctor --fix` | Auto-repair diagnostics |
| `python -m cli.main guard check -c "rm -rf /"` | Evaluate command safety |

---

## Architecture

```text
weebot/
├── domain/                  # Pure business logic
│   ├── models/              # Pydantic entities, events, reviews, contracts
│   ├── ports.py             # Domain protocol ports
│   └── services/            # Pure domain services
├── application/             # Use cases and orchestration
│   ├── di/                  # Dependency-injection container
│   ├── ports/               # Application ABC ports
│   ├── flows/               # PlanActFlow, ChatFlow, state machines
│   ├── agents/              # Planner, Executor, Critic, Dreamer, Retention
│   ├── middleware/          # Middleware stack
│   ├── cqrs/                # Mediator, commands, queries, handlers
│   ├── services/            # Application services
│   └── skills/              # Skill registry and converters
├── infrastructure/          # Adapters for LLMs, persistence, events, sandbox
├── interfaces/              # Entry points
│   ├── cli/                 # AgentRunner, behavior commands
│   ├── web/                 # FastAPI + WebSocket + SSE
│   └── gateways/            # Discord, Slack, Telegram
├── tools/                   # Agent-callable tools (port-based)
├── skills/builtin/          # Built-in skill packages
├── mcp/                     # MCP server implementation
└── config/                  # Settings, model registry, prompts
```

**Dependency rule:** `Domain` ← `Application` ← `Infrastructure` ← `Interfaces`. Boundaries are enforced by `import-linter` and architecture fitness tests in CI.

---

## Operational Flow

```text
User Prompt
    │
    ▼
PlanningState
    │
    ▼
CritiquingState          # Plan validation against confidence thresholds
    │
    ▼
PremortemState           # Failure-mode injection
    │
    ▼
ExecutingState           # Parallel tool execution
    │   │
    │   ├── StepResultValidator
    │   ├── CodeReviewerService
    │   └── TrajectoryMonitor
    │
    ▼
UpdatingState            # Tree-of-Thoughts revision on failure
    │
    ▼
VerifyingState           # CoVe fact-checking
    │
    ▼
SummarizingState
    │
    ▼
CompletedState
    │
    ├── TrustReport      # clean / watch / investigate
    ├── RetentionAgent   # keep / improve / park / prune
    └── DreamerAgent     # Auto-scan for new ideas
```

---

## Built-in Skills

| Skill | Use case |
|---|---|
| `seo_optimizer` | Technical SEO audit, keyword research, structured data, sitemaps |
| `reify_skill` | YouTube video → transcript → summary → actionable persistent rules |
| `architecture_design` | Pattern selection, layer boundaries, ADR generation |
| `tdd_app_dev` | Red-Green-Refactor development for Python, JS, and TS |
| `orchestration_guide` | Parallel task design, file partitioning, synthesis strategy |
| `git-best-practices` | Conventional commits, branching, secrets safety |
| `design-taste-frontend` | Anti-slop frontend design and visual quality enforcement |
| `web_research` | Multi-engine search + browser-based research |
| `competitive_analysis` | Swarm-based clustering and whitespace identification |
| `reasoner` | 24 reasoning methods across 46 presets |
| `multi_llm_orchestrator` | Full-stack delegation through a multi-LLM pipeline |
| `berb-research` | 23-stage autonomous academic research pipeline |

---

## Security Model

Command and code execution passes through four defensive layers:

```text
User Command
    │
    ▼
BashGuard
    │   # 40+ regex patterns across 6 risk categories
    ▼
CommandSecurityAnalyzer
    ├── Layer 1: Syntax pattern matching (bash + PowerShell)
    ├── Layer 2: Behavioral analysis (download-and-execute chains)
    ├── Layer 3: Entropy analysis (base64-like obfuscation)
    └── Layer 4: Semantic validation (chain length, URL detection)
    │
    ▼
FilesystemPermission
    │   # Declarative allow / deny / interrupt on paths
    ▼
ExecApprovalPolicy
    │   # DENY / ALWAYS_ASK / AUTO_APPROVE
    ▼
SandboxPort
    │   # Timeout, output limits, network gating
    ▼
Execution
```

API keys are loaded through `WeebotSettings`, redacted in exceptions, and never logged. The FastAPI CORS configuration requires explicit origins and forbids `allow_credentials=True` with `"*"`.

---

## Testing

```bash
# Run the full suite
pytest tests/ -v

# Unit tests with coverage
pytest tests/unit/ -v --tb=short --cov=weebot --cov-report=term --cov-fail-under=60

# Architecture gates
pytest tests/unit/test_architecture_fitness.py -v

# Skip slow tests
pytest tests/ -v -m "not slow"

# Import-lint architecture contracts
make lint-imports
```

---

## Deployment

### Docker Compose

```bash
docker compose up --build
```

This starts the FastAPI backend on port `8000` and the Next.js frontend on port `80`.

### Manual services

```bash
# Backend
python -m weebot.interfaces.web.main

# Frontend
cd weebot-ui
npm install
npm run dev
```

### MCP Server

```bash
python run_mcp.py
```

---

## Development

- Read `AGENTS.md` for the complete contributor guide, architecture rules, and conventions.
- Follow the Clean Architecture dependency rule for all new code.
- Add unit tests for domain and application changes; integration tests for new adapters and flows.
- Run `make check` before opening a PR: it runs tests, architecture gates, and import-linting.

---

## License

See the repository's `LICENSE` file for licensing terms.

---

*Weebot — Clean Architecture · CQRS · Middleware orchestration · Self-evolving skills · Multi-model cost cascade*
