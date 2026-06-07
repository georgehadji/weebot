# Weebot — Enterprise AI Agent Framework

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](.python-version)
[![Version](https://img.shields.io/badge/version-3.1.0-blue)]
[![Tests](https://img.shields.io/badge/tests-1,200%2B%20passing-success)]
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Clean Architecture](https://img.shields.io/badge/architecture-Clean%20%7C%20Hexagonal-8A2BE2)]

**A production-grade framework for building autonomous AI agents** with Clean Architecture, CQRS/event-driven orchestration, multi-model cost optimization, secure sandboxed execution, self-evolving skills, and Hermes-compatible SOUL.md identity.

→ [Quick Start](#quick-start) · [Use Cases](#use-cases) · [CLI Overview](#cli-overview) · [Architecture](#architecture) · [Why Weebot](#why-weebot) · [Documentation](docs/)

---

## Why Weebot

| Concern | Weebot | DIY / LangChain |
|---------|--------|-----------------|
| **Architecture degrades over time** | Fitness tests enforce Clean Architecture rules in CI — violations fail the build | No structural enforcement; coupling grows with every feature |
| **LLM costs spiral** | Automatic FREE→Budget→Premium model cascading with per-task cost budgets | You build your own routing — or use one model for everything |
| **Agent skills don't improve** | SkillOpt optimizer automatically improves skills from execution trajectories | No mechanism to learn from failures |
| **Hard to audit what agents did** | Full CQRS event stream with SQLite audit trail, Parquet analytics export, OTel tracing | Ad-hoc logging; no structured event history |
| **Shell execution is a security risk** | 4-tier risk classification, 40+ attack patterns, standalone bash guard CLI, sandboxed execution, approval gates | `subprocess.run()` — you build the guardrails |
| **Agent identity is hardcoded** | SOUL.md free-form persona files — Hermes-compatible, per-profile, hot-reloaded | System prompt strings scattered across config |
| **Two parallel systems emerge** | 4-phase Architecture Remediation unified dual event buses, state management, and persistence | Accumulates technical debt until a rewrite |

**Built on a verified foundation:** The codebase underwent a complete forensic architecture audit resolving 4 CRITICAL and 8 HIGH findings. All architectural rules are enforced by automated fitness tests in CI.

---

## Use Cases

**Automated Code Review & Fixing**
Feed a PR diff to a planner-executor agent loop; the agent analyzes, proposes changes, runs tests, and iterates. All tool calls are sandboxed; all decisions are traceable through the CQRS event stream.

**Research & Synthesis**
Deploy a researcher agent with web search, browser inspection, file I/O, and video transcription tools. Output is a structured report. Multi-agent orchestration via `swarm` and `debate` tools enables parallel investigation.

**DevOps & Infrastructure Automation**
Schedule agents to monitor systems, rotate secrets, enforce compliance policies, and remediate drift. Bash/PowerShell execution is sandboxed with 4-tier risk gates; approval workflows prevent destructive actions. Use `weebot guard check` to audit any shell command before execution.

**Custom Skill Pipelines**
Use SkillOpt to train specialized skills from trajectory data. A skill is a markdown prompt — deploy it and the optimizer iteratively improves it from real execution failures, with held-out validation preventing regression. Import skills from Manus, MyManus, AgenticSeek, and OpenClaw formats.

**Agent Identity & Persona Management**
Define agent personalities with SOUL.md files (Hermes-compatible). Per-profile identities (`~/.weebot/profiles/<name>/SOUL.md`) let different agents embody different personas — a terse Go expert, a warm support assistant, a rigorous code reviewer — while sharing the same WEEBOT_CORE.md safeguards.

---

## Features

### Core Platform
| Capability | Detail |
|-----------|--------|
| **Clean Architecture** | Domain → Application → Infrastructure → Interfaces with automated fitness test enforcement |
| **CQRS + Mediator** | 17 commands, 12 queries with pipeline behaviors (logging, validation, telemetry, save policy) |
| **Event-Driven** | 19 event types through unified `AsyncEventBus`; SQLite-backed audit trail; Parquet analytics export |
| **Multi-Model Routing** | 58+ models via OpenRouter with automatic FREE→Budget→Premium cascading; cost dashboard |
| **Secure Execution** | Sandboxed Bash/Python/PowerShell via `SandboxPort` (Native Windows, WSL2, Docker) |
| **Self-Evolving Skills** | SkillOpt optimizer — autonomous skill improvement from execution trajectories |
| **MCP Server** | 7 resources (`activity`, `state`, `schedule`, `products`, `tools`, `costs`, `skills`) + 36 auto-registered tools |
| **Web Dashboard** | FastAPI + Next.js 14 with real-time WebSocket streaming; ops console API |
| **SOUL.md Identity** | Hermes-compatible free-form persona files — per-profile, hot-reloaded, injection-scanned |
| **Flow Checkpoint/Resume** | Crash recovery — save flow state after each step; resume from last checkpoint |
| **Flow Serializer** | Export completed flows as Mermaid diagrams, JSON traces, or LangGraph definitions |

### CLI Toolbox
| Command | Description |
|---------|-------------|
| `flow run` | Execute a task with PlanActFlow |
| `flow list/resume/cancel` | Manage agent sessions |
| `guard check -c "..."` | Evaluate shell command safety (4-tier, supports `--json`, `--verbose`, stdin pipe) |
| `soul show/edit/seed/list` | Manage SOUL.md agent identity files |
| `analytics query "<sql>"` | DuckDB queries over Parquet event exports |
| `analytics dashboard` | Rich terminal dashboard of event stats |
| `doctor --fix --dry-run` | Auto-repair workspace directories, DB schema, `.env` template |
| `skill install/update/test` | Manage skills from SkillHub |
| `health` | Per-component health checks with Prometheus metrics |
| `agents list/route` | Persona registry and task routing |

### Security
- **4-tier bash safety** — SAFE / SUSPICIOUS / DANGEROUS / BLOCKED with 40+ attack patterns
- **Standalone bash guard CLI** — `weebot guard check` evaluates any command from stdin or args
- **SandboxPort abstraction** — all tool execution routes through configurable sandbox (native, WSL2, Docker)
- **SOUL.md injection scanning** — persona files scanned for prompt injection patterns before injection
- **Exec approval policies** — rule-based gates for destructive commands with user confirmation

### Observability
- **Events** — every agent action produces a structured `AgentEvent` persisted to SQLite
- **Prometheus metrics** — LLM calls, tool executions, session activity, circuit breaker state
- **OpenTelemetry export** — optional OTLP gRPC sink for Jaeger/Grafana/Honeycomb (`WEEBOT_OTEL_ENDPOINT`)
- **Parquet analytics** — long-term event storage with DuckDB query support
- **Cost tracking** — per-session, per-model cost ledger; cascade hit-rate dashboard
- **Health checks** — component-level status with JSON output for monitoring systems

### Architecture Quality (verified in CI)
| Gate | Enforcement |
|------|-----------|
| Domain imports nothing from outer layers | AST-based fitness test |
| Application imports infrastructure only in function bodies | AST-based fitness test |
| Every command/query has a registered handler | AST-based fitness test |
| Only `di.py` creates infrastructure adapters | Single composition root |
| Flow states use `mediator.send()`, not direct agent calls | AST-based fitness test |
| Tools use ports, not direct `sqlite3` imports | AST-based fitness test |
| No `__import__()` hacks in application code | Zero remaining |
| Import-linter contracts (5 rules) | CI gate |

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/georgehadji/weebot.git
cd weebot
pip install -r requirements.txt
cp .env.example .env   # Edit with your API keys
```

### 2. Verify

```bash
python -m cli.main health
python -m cli.main doctor
```

### 3. Set Your Agent Identity

```bash
# Create and edit your SOUL.md persona
python -m cli.main soul seed
python -m cli.main soul edit
```

### 4. Run a Task

```bash
python -m cli.main flow run "Analyze the test suite and report coverage gaps"
```

### 5. (Optional) Start the Dashboard

```bash
# Terminal 1 — API server
python -m weebot.interfaces.web.main

# Terminal 2 — Frontend
cd weebot-ui && npm run dev
```

### Configuration

```bash
# .env — minimum viable config
OPENROUTER_API_KEY=sk-or-v1-...

# Optional: observability
WEEBOT_OTEL_ENDPOINT=http://localhost:4317    # OTel traces
WEEBOT_ANALYTICS_DIR=./analytics              # Parquet event export
```

See `weebot/config/settings.py` for all options (model cascading, security policies, budget limits, cache tuning, sandbox mode).

---

## Architecture

```
weebot/
├── domain/              # Business entities & ports (pure Pydantic, zero outer deps)
│   ├── models/          # Session, Plan, Step, AgentEvent (19 types), Skill, Trajectory,
│   │                      SoulProfile, ToolManifest, FlowCheckpoint
│   ├── ports.py         # 5 Protocol ports (IModelProvider, IRepository, INotifier, ITool, EventPublisher)
│   └── services/        # WorkingMemory, HumanInteraction, SessionMemory
├── application/         # Use cases & orchestration
│   ├── cqrs/            # Mediator · 17 commands · 12 queries · 20 handlers
│   ├── flows/           # PlanActFlow, ChatFlow, SkillOptFlow, HyperAgentFlow, WorkflowPlanner
│   ├── agents/          # Planner, Executor, StructuredExecutor, Optimizer, ChatAgent, HyperAgent
│   ├── services/        # TaskRunner, FlowSerializer, MemoryCompactor, PlanCritic, +30 more
│   ├── ports/           # 15 ABC interfaces (LLMPort, SandboxPort, AnalyticsSinkPort, CheckpointPort,
│   │                      SoulProviderPort, ToolDiscoveryPort, ScoringPort, TracingPort, …)
│   └── di/              # Single composition root (Container + 5 mixins)
├── infrastructure/      # Adapters for LLMs, persistence, sandbox, events, analytics
│   ├── adapters/        # OpenRouter, Anthropic, DeepSeek, OpenAI, Moonshot — with resilient wrapper
│   │                      ToolDiscoveryAdapter, FileSystemSoulProvider
│   ├── persistence/     # SQLiteStateRepository, SkillStore, TrajectoryRepo, CheckpointStore, Cache
│   ├── sandbox/         # NativeWindowsSandbox, WSL2Sandbox, DockerLinuxSandbox
│   ├── analytics/       # ParquetActivitySink — partitioned event export
│   ├── observability/   # Prometheus metrics, health checks, OtelActivitySink
│   └── events/          # AsyncEventBus, EventBrokerAdapter
├── interfaces/          # CLI (Rich), Web (FastAPI+WS), MCP Server, Discord gateway
│   └── web/routers/     # sessions, models, health, dashboard, behavior, chat, SSE, ops, discord
├── tools/               # 36 agent-callable tools (bash, python, web, file, browser, swarm, …)
├── mcp/                 # MCP server — 7 resources, auto-registered tools
├── skills/              # Built-in skills (design-taste, git-best-practices, reasoner, …)
└── core/                # bash_guard, circuit_breaker, model_cascade_tracker, approval, safety
```

**Layer dependency rule:** `Domain ← Application ← Infrastructure ← Interfaces` — verified by automated CI tests. See [docs/ARCHITECTURE.md](ARCHITECTURE.md) for the full reference and `docs/codebase_mindmap.md` for the module inventory.

---

## MCP Server

Weebot exposes a Model Context Protocol server with 7 resources and 36 auto-discovered tools:

| Resource | Description |
|----------|-------------|
| `weebot://activity` | Recent agent activity events (newest-first) |
| `weebot://state` | Agent state snapshot (projects, status) |
| `weebot://schedule` | Scheduled jobs list |
| `weebot://products` | Product requirements roadmap |
| `weebot://tools` | 36-tool catalog with role access and safety flags |
| `weebot://costs` | Cascade stats, per-tier outcomes, cost estimates |
| `weebot://skills` | Installed skills with versions and triggers |

```bash
# Start MCP server (stdio — for Claude Desktop)
python -m weebot.mcp.server

# Or SSE transport
python -m weebot.mcp.server --transport sse --port 8765
```

---

## Testing

```bash
# Full suite
pytest tests/ -v

# Architecture fitness (CI gate)
pytest tests/unit/test_architecture_fitness.py -v

# Bash guard CLI tests
pytest tests/unit/test_bash_guard_cli.py -v

# Event bridge contract tests
pytest tests/integration/test_event_bridge_contract.py -v

# With coverage
pytest tests/ --cov=weebot --cov-report=html
```

**1,200+ tests** · 18 architecture fitness tests · 11 bash guard CLI tests · 6 event contract tests · 102 SkillOpt tests.

---

## SkillOpt — Self-Evolving Skills

Weebot implements the SkillOpt algorithm (Yang et al., Microsoft) for automatic skill improvement:

1. **Rollout** — execute training tasks with current skill → collect trajectories
2. **Reflect** — optimizer analyzes failures/successes, proposes edits
3. **Validate** — held-out tasks gate acceptance (ties rejected)
4. **Deploy** — only strictly-improving skills are promoted

```bash
# Optimize a skill
python -m cli.main skill optimize my_skill --epochs 4

# Transfer to a different model
python -m cli.main skill transfer my_skill --target-model gpt-4o

# Import from external formats
python -m cli.main skill install ./path/to/manus-skill
```

See `docs/MANUS_SKILL_ECOSYSTEM_ENHANCEMENTS.md` for the skill converter reference.

---

## Project Status

| Phase | Scope | Status |
|-------|-------|--------|
| **1–4. Architecture Remediation** | StateManager removal, CQRS handlers, layer classification, fitness tests, Prometheus metrics, web API auth | ✅ |
| **5–7. Core Platform** | Computer use tools, workflow orchestrator, template stack, observability modules | ✅ |
| **10-Enhancements** | MCP auto-registration, OTel/Parquet sinks, Flow Checkpoint/Resume, Flow Serializer, Cascade Tracker, Bash Guard CLI, Doctor --fix, Ops Console API, Skill Marketplace resource, SOUL.md identity | ✅ |

**Next:** Plugin system · Cross-model skill transfer · Multi-agent coordination

---

## License

MIT — see [LICENSE](LICENSE).

---

*Weebot v3.1 · Architecture fitness-verified · CQRS/event-driven · Self-evolving skills · SOUL.md · Sandboxed execution*
