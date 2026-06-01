# Weebot — Enterprise AI Agent Framework

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](.python-version)
[![Version](https://img.shields.io/badge/version-3.0.0-blue)]
[![Tests](https://img.shields.io/badge/tests-1,200%2B%20passing-success)]
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Clean Architecture](https://img.shields.io/badge/architecture-Clean%20%7C%20Hexagonal-8A2BE2)]

**A production-grade framework for building autonomous AI agents** with Clean Architecture, CQRS/event-driven orchestration, multi-model cost optimization, secure sandboxed execution, and self-evolving skills.

→ [Quick Start](#quick-start) · [Use Cases](#use-cases) · [Architecture](#architecture) · [Why Weebot](#why-weebot) · [Documentation](docs/)

---

## Why Weebot

| Concern | Weebot | DIY / LangChain |
|---------|--------|-----------------|
| **Architecture degrades over time** | Fitness tests enforce Clean Architecture rules in CI — violations fail the build | No structural enforcement; coupling grows with every feature |
| **LLM costs spiral** | Automatic FREE→Budget→Premium model cascading with per-task cost budgets | You build your own routing — or use one model for everything |
| **Agent skills don't improve** | SkillOpt optimizer automatically improves skills from execution trajectories (paper-implemented) | No mechanism to learn from failures |
| **Hard to audit what agents did** | Full CQRS event stream with SQLite audit trail and cost tracking | Ad-hoc logging; no structured event history |
| **Shell execution is a security risk** | 4-tier risk classification, 40+ attack patterns, sandboxed execution, approval gates | `subprocess.run()` — you build the guardrails |
| **Two parallel systems emerge** | 4-phase Architecture Remediation unified dual event buses, state management, and persistence | Accumulates technical debt until a rewrite |

**Built on a verified foundation:** The codebase underwent a complete forensic architecture audit (June 2026) resolving 4 CRITICAL and 8 HIGH findings. All architectural rules are enforced by 12 automated fitness tests in CI.

---

## Use Cases

**Automated Code Review & Fixing**
Feed a PR diff to a planner-executor agent loop; the agent analyzes, proposes changes, runs tests, and iterates. All tool calls are sandboxed; all decisions are traceable through the CQRS event stream.

**Research & Synthesis**
Deploy a researcher agent with web search, browser inspection, file I/O, and video transcription tools. Output is a structured report with citations. Multi-agent orchestration enables parallel investigation across sources.

**DevOps & Infrastructure Automation**
Schedule agents to monitor systems, rotate secrets, enforce compliance policies, and remediate drift. Bash/powerShell execution is sandboxed with 4-tier risk gates; approval workflows prevent destructive actions.

**Custom Skill Pipelines**
Use SkillOpt to train specialized skills from trajectory data. A skill is a markdown prompt — deploy it and the optimizer iteratively improves it from real execution failures, with held-out validation preventing regression.

---

## Features

### Core Platform
| Capability | Detail |
|-----------|--------|
| **Clean Architecture 🏛️** | Domain → Application → Infrastructure → Interfaces with automated fitness test enforcement in CI |
| **CQRS + Mediator ⚡** | 14 commands, 9 queries with pipeline behaviors (logging, validation, telemetry) |
| **Event-Driven 🔄** | 19 event types through unified `AsyncEventBus`; SQLite-backed audit trail |
| **Multi-Model Routing 🧠** | 58+ models via OpenRouter with automatic FREE→Budget→Premium cascading |
| **Secure Execution 🛡️** | Sandboxed Bash/Python/PowerShell via `SandboxPort` abstraction (Native Windows, WSL2, Docker) |
| **Self-Evolving Skills 📈** | SkillOpt optimizer (Yang et al., arXiv:2605.23904v2) — autonomous skill improvement from trajectories |
| **MCP Server 🔌** | Expose weebot tools over Model Context Protocol for Claude Desktop / IDE integration |
| **Web Dashboard 📊** | FastAPI + Next.js 14 with real-time WebSocket event streaming |

### Security
- **4-tier bash safety** — SAFE / SUSPICIOUS / DANGEROUS / BLOCKED with multi-layer pattern analysis
- **SandboxPort abstraction** — all tool execution routes through a configurable sandbox (native, WSL2, Docker)
- **Exec approval policies** — rule-based gates for destructive commands with user confirmation
- **State verification** — post-execution verification against claimed system state (arXiv:2602.20021)

### Observability
- **Events** — every agent action produces a structured `AgentEvent` persisted to SQLite
- **Prometheus metrics** — LLM calls, tool executions, session activity, event throughput
- **Cost tracking** — per-session, per-model cost ledger with budget enforcement
- **Health checks** — component-level status with JSON output for monitoring systems

### Architecture Quality (verified in CI)
| Gate | Enforcement |
|------|-----------|
| Domain imports nothing from outer layers | AST-based fitness test ✅ |
| Application imports infrastructure only in function bodies | AST-based fitness test ✅ |
| Every command/query has a registered handler | AST-based fitness test ✅ |
| Only `di.py` creates infrastructure adapters | Single composition root ✅ |
| Flow states use `mediator.send()`, not direct agent calls | AST-based fitness test ✅ |
| Tools use ports, not direct `sqlite3` imports | AST-based fitness test ✅ |
| No `__import__()` hacks in application code | Zero remaining ✅ |

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/your-org/weebot.git
cd weebot
pip install -r requirements.txt
cp .env.example .env   # Edit with your API keys
```

### 2. Verify

```bash
python -m cli.main health
```

### 3. Run a Task

```bash
python -m cli.main flow run "Analyze the test suite and report coverage gaps"
```

### 4. (Optional) Start the Dashboard

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
```

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for all options (model cascading, security policies, budget limits, cache tuning).

---

## Architecture

```
weebot/
├── domain/              # Business entities & ports (pure Pydantic, zero outer deps)
│   ├── models/          # Session, Plan, Step, AgentEvent (19 types), Skill, Trajectory
│   └── services/        # WorkingMemory, HumanInteraction, SessionMemory
├── application/         # Use cases & orchestration
│   ├── cqrs/            # Mediator · 14 commands · 9 queries · 17 handlers
│   ├── flows/           # PlanActFlow, ChatFlow, SkillOptFlow, WorkflowPlanner
│   ├── agents/          # Planner, Executor, StructuredExecutor, Optimizer, ChatAgent
│   ├── services/        # TaskRunner, ValidationRunner, ContextSwitcher, +22 more
│   ├── ports/           # 11 ABC interfaces (LLMPort, SandboxPort, ScoringPort, …)
│   └── di.py            # Single composition root ✅
├── infrastructure/      # Adapters for LLMs, persistence, sandbox, events, scoring
│   ├── adapters/        # OpenRouter, Anthropic, DeepSeek, OpenAI — with resilient wrapper
│   ├── persistence/     # SQLiteStateRepository, SkillStore, TrajectoryRepo, Cache
│   ├── sandbox/         # NativeWindowsSandbox, WSL2Sandbox, DockerLinuxSandbox
│   ├── events/          # AsyncEventBus, EventBrokerAdapter (bridge)
│   ├── scoring/         # ExactMatch, ExecutionResult, VerifierScorer
│   └── observability/   # Prometheus metrics, health checks
├── interfaces/          # CLI (Rich), Web (FastAPI+WS), MCP Server
├── tools/               # 20 agent-callable tools (bash, python, web, file, browser, …)
└── core/                # bash_guard, circuit_breaker, model_cascade, approval
```

**Layer dependency rule:** `Domain ← Application ← Infrastructure ← Interfaces` — verified by automated CI tests. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full reference.

---

## Testing

```bash
# Full suite
pytest tests/ -v

# Architecture fitness (CI gate)
pytest tests/unit/test_architecture_fitness.py -v

# Event bridge contract tests
pytest tests/integration/test_event_bridge_contract.py -v

# With coverage
pytest tests/ --cov=weebot --cov-report=html
```

**1,200+ tests** · 12 architecture fitness tests · 6 event contract tests · 102 SkillOpt tests · ~90% coverage on core paths.

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
python -m cli.main skill transfer my_skill --target-model gpt-5.4-mini
```

See [docs/SKILLOPT.md](docs/SKILLOPT.md) for the full algorithm reference.

---

## Project Status

All four phases of the Architecture Remediation (v2.8 → v3.0) are complete:

| Phase | Scope | Status |
|-------|-------|--------|
| **1. Stabilize** | StateManager removal, ScoringPort in DI, event bridge, CQRS handlers | ✅ |
| **2. Consolidate** | PlanActFlow extraction (3 services), SandboxPort in tools, StateCoordinator deprecated, `__import__()` eliminated, global singletons replaced with DI | ✅ |
| **3. Classify** | 27 files promoted to correct layers, 4 dead files deleted, import-linter contracts | ✅ |
| **4. Harden** | 12 architecture fitness tests, Prometheus metrics, web API auth, 5 ADRs, event reconstructor | ✅ |

**Next:** Plugin system (Phase 12) · Cross-model skill transfer (Enhancement #8) · Multi-agent coordination (Phase 13)

---

## License

MIT — see [LICENSE](LICENSE).

---

*Weebot v3.0 · Architecture fitness-verified · CQRS/event-driven · Self-evolving skills · Sandboxed execution*
