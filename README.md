# Weebot

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Code style](https://img.shields.io/badge/code%20style-ruff-000000)](https://docs.astral.sh/ruff/)
[![Architecture](https://img.shields.io/badge/architecture-Clean%20Hexagonal%20%7C%20CQRS-8A2BE2)](ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)](https://docs.pytest.org/)

Weebot is an autonomous AI agent framework. You give it a task in plain language; it plans the work, runs
it step by step with sandboxed tools, reviews and verifies its own output, and reports what it did. Every
step is recorded as an event, so a run can be inspected, resumed or exported afterwards.

You can use it four ways:

| Interface | Start with | Best for |
|---|---|---|
| **Web UI** | backend + `npm run dev` | Day-to-day use: watch a run live, steer it, manage models |
| **CLI** | `python -m cli.main flow run "..."` | One-shot tasks and scripting |
| **Interactive terminal** | `python run.py --interactive` | A conversational session in the terminal |
| **MCP server** | `python run_mcp.py` | Exposing Weebot's tools to another MCP client |

Chat gateways (Telegram, Slack, WhatsApp, Signal, Email) run inside the web backend.

## Contents

- [Quick start](#quick-start)
- [Starting Weebot](#starting-weebot)
- [Using the web UI](#using-the-web-ui)
- [Using the CLI](#using-the-cli)
- [Choosing models](#choosing-models)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Chat gateways](#chat-gateways)
- [Docker](#docker)
- [How it works](#how-it-works)
- [Security model](#security-model)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Quick start

**Requirements**

- Python 3.12 or newer
- At least one model provider key (OpenRouter is the simplest: one key reaches many models)
- Node.js 20 or newer, only for the web UI

**Install**

```bash
git clone https://github.com/georgehadji/weebot.git
cd weebot
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and set one provider key:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

**Check the install**

```bash
python -m cli.main health
python run.py --diagnostic
```

**Run a first task**

```bash
python -m cli.main flow run "List the Python files in this folder and summarise what each one does"
```

---

## Starting Weebot

Everything below is started from the repository root with the virtual environment active.

### Web UI (backend + frontend)

Weebot's web UI needs two processes: the API on port 8000 and the UI on port 3000. Use two terminals.

**Terminal 1: backend**

```bash
python -m weebot.interfaces.web.main
```

This serves the API at `http://127.0.0.1:8000` and reloads on code changes. It reads `WEEBOT_PORT` for the
port and binds to loopback by default. To run without auto-reload, for example on a server:

```bash
uvicorn weebot.interfaces.web.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2: frontend** (first run installs dependencies)

```bash
cd weebot-ui
npm install
npm run dev
```

Open **http://localhost:3000**. For a production build use `npm run build` and then `npm run start`
(serves on `127.0.0.1:3000`).

The UI finds the backend at `http://localhost:8000` and `ws://localhost:8000/ws`. If the backend is elsewhere,
set `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` before `npm run dev` or `npm run build`.

### Terminal

| Goal | Command |
|---|---|
| Run one task and exit | `python -m cli.main flow run "task"` |
| Conversational session | `python run.py --interactive` |
| Interactive session with a skill | `python run.py --interactive --skill seo_optimizer` |
| Interactive session on a chosen model | `python run.py --interactive --model <model-id>` |
| Self-test | `python run.py --diagnostic` |

### MCP server

```bash
python run_mcp.py
```

Supports stdio and SSE. For SSE, set `WEEBOT_MCP_API_KEY`. A sample client config is in
`claude_desktop_config.json.example`.

### Everything at once

`docker compose up --build` starts the API, the UI and the event bus together. See [Docker](#docker).

---

## Using the web UI

1. **Start a task.** On the home page, type what you want in the message box and send it. A session is
   created and named from your first line.
2. **Watch it work.** The conversation shows the plan, each step, every tool call with its result, and any
   errors. Long runs keep scrolling with the newest event; if you scroll up to read, a button appears to jump
   back to the latest.
3. **Steer it.** Use the run controls to cancel, resume or answer a question the agent has asked. Plans that
   need approval are shown as a card you can accept or send back with changes.
4. **Find earlier work.** The left rail lists sessions; the search box filters them by title and prompt.
5. **Inspect details.** The right dock shows the plan, tools used, cost and trust information for the open
   session.
6. **Command palette.** Press `Ctrl+K` (`Cmd+K` on macOS) from any page to jump between sessions and pages.

Other pages:

| Page | Purpose |
|---|---|
| `/models` | The model catalogue, and the per-role model picker (see below) |
| `/ops` | Operational dashboard: metrics, costs, health |

---

## Using the CLI

### Running and managing tasks

| Command | Description |
|---|---|
| `python -m cli.main flow run "task"` | Run a task. Options: `--model <id>`, `--session-id <id>` |
| `python -m cli.main flow list` | List active and waiting sessions |
| `python -m cli.main flow resume <id> "answer"` | Answer a paused session and continue |
| `python -m cli.main flow cancel <id>` | Cancel a running session |
| `python -m cli.main flow retry <id>` | Retry a failed session |
| `python -m cli.main flow undo <id>` | Undo the last plan change |
| `python -m cli.main flow search "text"` | Full-text search across sessions |
| `python -m cli.main flow export <id>` | Export a session's events to JSONL |
| `python -m cli.main costs` | Show spend by model |

### Skills, personas and ideas

| Command | Description |
|---|---|
| `python -m cli.main skill list` | List installed skills |
| `python -m cli.main flow skillopt <name>` | Improve a skill from past runs |
| `python -m cli.main agents list` | List agent personas |
| `python -m cli.main agents route "task"` | Pick the best persona for a task |
| `python -m cli.main dream scan` | Look for improvement ideas from past failures |
| `python -m cli.main dream list` | List pending ideas |
| `python -m cli.main dream build <id>` | Execute an approved idea |

### Setup and diagnostics

| Command | Description |
|---|---|
| `python -m cli.main init` | Initialise a Weebot project in the current directory |
| `python -m cli.main health` | Check each component |
| `python -m cli.main doctor` | Diagnose the environment (`--fix` repairs what it can) |
| `python -m cli.main guard check -c "<command>"` | Show how the safety guard rates a shell command |
| `python -m cli.main auth --help` | Manage per-user API keys |
| `python -m cli.main gateway --help` | Manage chat allowlists and sessions |

Run `python -m cli.main --help` for the full list, or add `--help` to any command.

---

## Choosing models

Each agent role (planner, executor, coder, reviewer, verifier, summarizer and so on) has a built-in list of
models: a first choice and fallbacks. When a model fails or runs out of quota, the next one is tried.

**From the web UI.** Open `/models`. The **Agent models** panel has a dropdown for every role, split into
agents and sub-agents. Pick a model to make it that role's first choice; the built-in models stay behind it
as fallbacks. **Reset** returns the role to its default. Picks are stored in `.weebot/role_models.json` and
apply to new runs. Services the backend builds once at startup keep their model until you restart it.

**Local models with Ollama.** Weebot can send selected roles to a model on your own machine, or to an Ollama
cloud model. It is off by default. See [docs/OLLAMA.md](docs/OLLAMA.md).

**Cost control.** `DAILY_AI_BUDGET` caps daily spend, and circuit breakers stop repeated failing calls.

---

## Configuration

Settings are read from `.env`. The most useful ones:

| Variable | Purpose | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | One key for many models | none |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `KIMI_API_KEY` | Direct provider access | none |
| `WEEBOT_WORKSPACE` | Folder the agent may read and write | current directory |
| `WEEBOT_SESSIONS_DB` | Session database (SQLite) | `./weebot_sessions.db` |
| `WEEBOT_LOGS_DIR` | Log folder | `./logs` |
| `WEEBOT_PORT` | Backend port | `8000` |
| `DAILY_AI_BUDGET` | Daily spend limit in USD | `10.0` |
| `BASH_TIMEOUT`, `PYTHON_TIMEOUT` | Time limit per shell or Python run, seconds | `30` |
| `SANDBOX_ALLOW_NETWORK` | Let sandboxed code reach the network | `false` |
| `WEEBOT_API_KEY` | Protects the web API (see below) | none |
| `WEEBOT_MCP_API_KEY` | Protects the MCP SSE transport | none |

`.env.example` lists every variable. [docs/CONFIGURATION.md](docs/CONFIGURATION.md) explains them.

---

## Authentication

By default the web API listens on loopback only. With no `WEEBOT_API_KEY` set, requests from other machines
are refused and changes (creating sessions, picking models) are allowed only from the local machine.

To use Weebot from another machine or behind a proxy:

1. Set `WEEBOT_API_KEY` in `.env` and restart the backend.
2. Bind to a reachable address (`WEEBOT_WEB_HOST`) and add your UI origin with `WEEBOT_CORS_ORIGIN`.
3. In the web UI, enter the key in the connection status control. It is kept for the browser tab only and
   sent as `X-API-Key`.

For several users, set `WEEBOT_AUTH_MODE=store` and issue one key per person with
`python -m cli.main auth`.

---

## Chat gateways

Gateways run inside the web backend, so start it first (`python -m weebot.interfaces.web.main`).

| Platform | What to set up |
|---|---|
| **Telegram** | Create a bot with [@BotFather](https://t.me/BotFather) and set `TELEGRAM_BOT_TOKEN`. It long-polls; no public URL needed. |
| **Slack** | Create an app with the Events API, subscribe to `message.channels` and `app_mention`, and set the request URL to `https://<host>/api/gateway/slack/events`. Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`. A public or tunnelled host is required (for example `ngrok http 8000`). |
| **WhatsApp** | Create a Meta app with WhatsApp enabled. Webhook URL: `https://<host>/api/gateway/whatsapp/webhook`. Set `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_BUSINESS_API_TOKEN`, `WHATSAPP_BUSINESS_PHONE_NUMBER_ID`; `WHATSAPP_APP_SECRET` is optional and enables signature checks. |
| **Signal** | Run [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) linked to a number; set `SIGNAL_CLI_REST_URL` and `SIGNAL_ACCOUNT_NUMBER`. |
| **Email** | Set `EMAIL_IMAP_USER`, `EMAIL_IMAP_PASSWORD` (an app password if you use 2FA) and the IMAP/SMTP servers. It never replies to itself or to automated senders. |

**Access control.** Chats are denied until you allow them:

```bash
python -m cli.main gateway allowlist add --platform telegram --id <chat_id>
python -m cli.main gateway allowlist list
python -m cli.main gateway sessions list
```

Supported platforms for `--platform`: `telegram`, `slack`, `whatsapp`, `signal`, `email`. Set
`WEEBOT_GATEWAY_AUTH_ENABLED=0` only for a private, single-user setup.

---

## Docker

```bash
cp .env.example .env        # add your provider key
docker compose --env-file .env up --build
```

| Service | Port | Notes |
|---|---|---|
| `weebot-api` | 8000 | FastAPI backend. Read-only root filesystem, non-root user. Keep it at **one replica**. |
| `weebot-ui` | 3000 | Next.js frontend |
| `weebot-valkey` | none published | Event bus; Weebot falls back to in-memory events without it |

Set `VALKEY_PASSWORD` for anything beyond local use. Data lives in the `weebot_data` volume. More in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## How it works

A task moves through a typed state machine:

```text
Plan -> Critique -> Pre-mortem -> Execute -> Review -> Verify -> Summarize -> Complete
                                      |
                                      +-- on failure: revise the plan and retry
```

- **Planning and critique.** A planner drafts the steps; a critic and a pre-mortem look for weaknesses
  before anything runs.
- **Execution.** Tools run in a sandbox. Each step is reviewed, and its output is checked against the
  evidence it produced.
- **Learning.** After a run, Weebot writes down what worked and what failed. Those notes are kept per
  project and shown to the planner in later sessions. Skills can be distilled from runs and improved with
  `flow skillopt`.
- **Audit trail.** Every plan, tool call and result is an event in SQLite, so any session can be replayed,
  resumed or exported.

The code follows Clean (hexagonal) Architecture. Dependencies point inward only:

```text
domain  <-  application  <-  infrastructure  <-  interfaces
```

```text
weebot/
  domain/           pure models and services
  application/      flows, agents, CQRS, dependency injection
  infrastructure/   model adapters, SQLite, sandbox, MCP, browser
  interfaces/       web API, CLI, gateways, MCP server
  tools/            tools the agent can call
  skills/builtin/   built-in skills
weebot-ui/          Next.js web UI
```

Import contracts and architecture tests enforce the dependency rule in CI. Diagrams and decisions are in
[ARCHITECTURE.md](ARCHITECTURE.md); a card for every concept is in [map/CLAUDE.md](map/CLAUDE.md).

### Built-in skills

Skills live in `weebot/skills/builtin/`. Examples: `seo_optimizer`, `architecture_design`, `tdd_app_dev`,
`web_research`, `competitive_analysis`, `reasoner`, `git-best-practices`, `design-taste`,
`multi_llm_orchestrator`, `berb-research`. List them with `python -m cli.main skill list`.

---

## Security model

Shell and code execution pass through several layers before anything runs:

1. **Bash guard.** Classifies each command as safe, suspicious, dangerous or blocked.
2. **Command analysis.** Pattern, behaviour, obfuscation and chain checks, for bash and PowerShell.
3. **Filesystem permissions.** Path rules that allow, deny or ask.
4. **Approval policy.** Deny, always ask, or auto-approve per action type.
5. **Sandbox.** Time limits, output limits and network gating.

Content fetched from outside (web pages, inbound mail) is treated as untrusted and cannot trigger actions
without review. API keys are loaded through the settings layer, redacted in errors and never logged. Details
and the fail-closed defaults are in [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md); report vulnerabilities
as described in [SECURITY.md](SECURITY.md).

---

## Development and testing

```bash
pytest tests/ -v                       # backend tests
make check                             # tests + architecture gates + lints
make lint-imports                      # layer contracts only
ruff check .                           # lint (line length 100)
```

`make` is not installed on every system (it is usually missing on Windows). Run the underlying commands
shown in the `Makefile` directly.

Frontend, from `weebot-ui/`:

```bash
npm run lint          # ESLint, including the layer rules
npm test              # unit and component tests
npm run test:e2e      # Playwright browser tests against a stubbed backend (no keys needed)
```

The first end-to-end run needs `npx playwright install chromium`. Contributor rules are in
[CONTRIBUTING.md](CONTRIBUTING.md) and [CLAUDE.md](CLAUDE.md); the UI's structure is in
[weebot-ui/README.md](weebot-ui/README.md); every command and entry point is listed in
[docs/ENTRY_POINTS.md](docs/ENTRY_POINTS.md).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No AI API keys configured` on start | Add a provider key to `.env`, then rerun `python -m cli.main health`. |
| UI loads but shows no data or a connection error | The backend is not running or not on port 8000. Start it, or set `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`. |
| `401` or `503` from the API | A non-local caller needs `WEEBOT_API_KEY` (see [Authentication](#authentication)). |
| `Address already in use` on 8000 or 3000 | Stop the other process, or set `WEEBOT_PORT` / run `npm run dev -- -p 3001`. |
| Console warning `data-sharkid` or a hydration mismatch | A browser extension is editing the page. Try a private window; the app is unaffected. |
| A model you picked is never used | Picks apply to new runs; restart the backend for services built at startup. |
| Anything else | `python -m cli.main doctor --fix`, then check the `logs/` folder. |

---

## License

See [LICENSE](LICENSE).
