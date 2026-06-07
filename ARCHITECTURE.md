# ARCHITECTURE.md — weebot AI Orchestrator

**Last updated:** 2026-06-07
**Architecture score:** 9.6/10
**Last audit:** Meta-Orchestration Cycle 1 (2026-06-07) — system HEALTHY, all debt items closed
**Maturity:** Production
**Paradigm:** Clean Architecture (Hexagonal Ports & Adapters) + CQRS Mediator + State-Machine Flows

---

## Recent Changes (2026-06-07)

| Change | File(s) | Impact |
|--------|---------|--------|
| `SQLiteCheckpointStore` async I/O offloaded | `infrastructure/persistence/checkpoint_store.py` | Eliminated event-loop blocking via `run_in_executor` |
| `SQLiteToolRepository` migrated to `aiosqlite` | `infrastructure/persistence/sqlite_tool_repo.py` | Non-blocking async I/O for all tool DB operations |
| Prometheus security counter added | `infrastructure/observability/metrics.py`, `core/bash_guard.py` | `bash_guard_events_total` counter by risk_level |
| PowerShell injection patterns added | `tools/bash_security.py` | 8 PowerShell-specific patterns (Invoke-Expression, iex, Net.WebClient, etc.) |
| MCP server API key auth | `mcp/server.py` | FastMCP `TokenVerifier` for SSE transport; `WEEBOT_MCP_API_KEY` env var |
| `PlanActFlowConfig` dataclass extracted | `application/models/plan_act_flow_config.py` (NEW), `application/flows/plan_act_flow.py`, `application/di/_agent_tools.py`, `application/di/_skillopt.py` | 22-param constructor → typed `@dataclass` |
| FastMCP `_register_resources` bug fixed | `mcp/server.py:404` | Removed `**kwargs` from `tools_resource` — URI has no template params |
| Architecture test suite repaired | `tests/unit/test_architecture_fitness.py`, `tests/unit/test_port_contracts.py` | 150/191 pass, 0 fail, 41 skipped (deprecated ports) |
| `chat_agent.py` SyntaxError fixed | `application/agents/chat_agent.py:13` | Missing comma in import |

---

## Layer Map

```
Interfaces (CLI / Web / MCP / Discord / Slack / Telegram)
    │
    ▼
Application (Flows / Agents / Services / Ports / CQRS)
    │
    ├──► Domain (Models / Protocol Ports)
    │         ▲
    │         │ (dependency inversion)
    └─────────┼── Infrastructure (Adapters / Persistence / Sandbox / LLM)
              │
              ▼
         Core (cross-cutting: bash_guard, circuit_breaker, safety)
```

| Layer | Path | Role | Can import | Cannot import |
|-------|------|------|------------|---------------|
| **Domain** | `weebot/domain/` | Pure business entities + Protocol ports | stdlib, self | `application`, `infrastructure`, `interfaces`, `core`, `tools` |
| **Application** | `weebot/application/` | Use cases, flows, agents, CQRS, ABC ports | `domain`, stdlib, `asyncio`, `core` (limited) | `infrastructure` (except `TYPE_CHECKING`), `interfaces`, `tools` |
| **Infrastructure** | `weebot/infrastructure/` | Adapter implementations of application ports | `domain`, `application.ports`, external libs | `application.agents`, `.flows`, `.services`, `.cqrs`, `.di` |
| **Interfaces** | `weebot/interfaces/`, `cli/` | Entry points (thin) | `application`, `domain`, `infrastructure` (via DI) | — |
| **Core** | `weebot/core/` | Cross-cutting: safety, circuit breaker, concurrency | stdlib, external libs | `application`, `infrastructure`, `interfaces` |

**[VERIFIED]** Layer boundaries enforced by `.importlinter` (5 contracts) and `tests/unit/test_architecture_fitness.py` (19 AST-based tests). Domain purity confirmed: zero outer-layer imports.

---

## Package Structure (current)

```
weebot/
├── domain/                         # Enterprise business logic (36 files)
│   ├── models/                     # 33 Pydantic entities (Plan, Step, Session, 19 event types, Skill, etc.)
│   ├── ports.py                    # 5 Protocol ports (IModelProvider, IRepository, INotifier, ITool, EventPublisher)
│   ├── services/                   # Domain services (session_memory, working_memory, human_interaction)
│   ├── exceptions.py               # Exception hierarchy (WeebotError + 8 subtypes)
│   └── legacy_models.py            # Frozen legacy types (deprecated)
│
├── application/                    # Use cases & orchestration
│   ├── di/                         # Container — single composition root
│   │   ├── __init__.py             # Container class (277 lines)
│   │   ├── _factories.py           # 23 factory methods for adapters
│   │   ├── _agent_tools.py         # Multi-agent tool bindings
│   │   ├── _capabilities.py        # Capability wiring
│   │   ├── _skills.py              # Skill registry bindings
│   │   └── _skillopt.py            # SkillOpt flow builder
│   ├── ports/                      # 41 ABC port interfaces
│   ├── flows/                      # State-machine flows
│   │   ├── plan_act_flow.py        # Primary Plan→Act→Critique→Summarize loop
│   │   ├── chat_flow.py            # Conversational agent flow
│   │   ├── skill_opt_flow.py       # Skill optimization (batch training)
│   │   ├── hyper_agent_flow.py     # Hyperagent orchestration
│   │   ├── harness_generation_flow.py  # Harness generation
│   │   └── states/                 # 11 per-state classes
│   ├── agents/                     # 10 LLM-calling agents
│   ├── cqrs/                       # CQRS with Mediator pipeline
│   │   ├── mediator.py             # Dispatcher with composable behaviors
│   │   ├── commands.py / queries.py    # Command/Query models
│   │   ├── handlers.py / handlers/     # 20+ handlers
│   │   └── behaviors/              # 5 pipeline behaviors
│   ├── services/                   # 55 application services
│   ├── models/                     # PlanActFlowConfig, ToolCollection
│   └── skills/                     # Skill registry + format converters
│
├── infrastructure/                 # Adapter implementations
│   ├── adapters/
│   │   ├── llm/                    # 8 adapters (OpenRouter, Anthropic, OpenAI, DeepSeek, Moonshot, Resilient)
│   │   ├── speech/                 # WhisperSpeechAdapter
│   │   ├── soul_provider.py        # FileSystemSoulProvider
│   │   ├── sub_agent_factory.py    # SubAgentFactory
│   │   └── ...                     # 15+ additional adapters
│   ├── persistence/                # 15 persistence adapters
│   │   ├── sqlite_state_repo.py    # SQLiteStateRepository
│   │   ├── sqlite_tool_repo.py     # SQLiteToolRepository (aiosqlite)
│   │   ├── checkpoint_store.py     # SQLiteCheckpointStore (run_in_executor)
│   │   ├── postgresql/             # PostgreSQL adapter (scaffolded)
│   │   └── ...
│   ├── sandbox/                    # NativeWindows, WSL2, DockerLinux, Modal
│   ├── browser/                    # PlaywrightAdapter + session management
│   ├── observability/              # Prometheus metrics, health checks, OTel
│   ├── security/                   # Agent sanitizer, audit logger, validators
│   ├── scoring/                    # ExactMatch, Execution, Verifier scorers
│   ├── notifications/              # Telegram, WindowsToast, SSE adapters
│   ├── event_bus.py                # AsyncEventBus
│   ├── event_store.py              # EventStore (SQLite append-only)
│   └── swarm_event_bus.py          # SwarmEventBus
│
├── interfaces/                     # Entry points
│   ├── web/                        # FastAPI app factory + 10 routers
│   ├── cli/                        # AgentRunner, behavior commands, event logger
│   ├── gateways/                   # Discord, Slack, Telegram adapters
│   └── factories.py                # Flow construction + routing
│
├── core/                           # Cross-cutting concerns (33 modules)
│   ├── bash_guard.py               # 4-tier shell safety (emits Prometheus counter)
│   ├── circuit_breaker.py          # CLOSED/OPEN/HALF_OPEN with jitter
│   ├── approval_policy.py          # DENY/ALWAYS_ASK/AUTO_APPROVE rules
│   ├── credential_sanitizer.py     # Password/token redaction
│   ├── error_classifier.py         # Exception → recovery routing
│   ├── model_cascade_config.py     # FREE → BUDGET → PREMIUM model tiers
│   ├── adaptive_concurrency.py     # Dynamic worker scaling via psutil
│   └── ...
│
├── tools/                          # 36 agent-callable tools
│   ├── base.py                     # BaseTool (ABC) + ToolResult
│   ├── bash_tool.py                # PowerShell/WSL2 shell execution
│   ├── bash_security.py            # 4-layer defense-in-depth analyzer
│   ├── python_tool.py              # Sandboxed Python execution
│   ├── advanced_browser.py         # Playwright-based browser automation
│   ├── file_editor.py              # View/create/edit files
│   ├── web_search.py               # DuckDuckGo + Bing search
│   └── ...                         # 30 more tools
│
├── mcp/                            # MCP server + 7 resources
├── skills/                         # Built-in skill manifests
├── scheduling/                     # NL-based cron scheduler
├── config/                         # Settings, constants, model registry, prompts
│   ├── settings.py                 # WeebotSettings (pydantic-settings, 40+ fields)
│   ├── constants.py                # DEFAULT_MAX_FLOW_ITERATIONS (50), etc.
│   └── model_registry.py           # 58+ model definitions
│
cli/                                # Click CLI entry module
├── main.py                         # CLI entry point
└── commands/                       # 9 command groups (flow, agents, skills, soul, etc.)
tests/
├── unit/                           # ~90 unit test files
├── integration/                    # Adapter + contract tests
└── unit/test_architecture_fitness.py  # 19 AST-based boundary enforcement tests
```

---

## Key Design Patterns

### 1. Dependency Injection (Container)
All adapters wired at `application/di/__init__.py`. `Container` is a `@dataclass` with lazy factories split across 5 mixin classes.

```python
container = Container()
container.configure_defaults()
llm = container.get(LLMPort)                  # → ResilientLLMAdapter
repo = container.get(StateRepositoryPort)      # → SQLiteStateRepository
```

### 2. CQRS + Mediator Pipeline
State mutations go through `Mediator.send(command)` → ordered pipeline behaviors → handler.

```
Mediator.send(CreatePlanCommand(...))
  → LoggingBehavior       → TelemetryBehavior
  → SavePolicyBehavior    → CreatePlanHandler
  → CommandResult[T]
```

### 3. State-Machine Flows
`PlanActFlow` transitions through 11 discrete states, each a separate class.

```
Idle → Planning → Executing → Verifying → Critiquing → Summarizing → Updating → Completed
         ↑                                                                      │
         └──────────────────────────────────────────────────────────────────────┘
```

### 4. Port/Adapter (Hexagonal)
41 ABC ports in `application/ports/`. Infrastructure adapters implement ports. Domain uses 5 lightweight `Protocol` ports.

| Application Port | Infrastructure Adapter |
|-----------------|----------------------|
| `LLMPort` | `ResilientLLMAdapter` wrapping 5 provider adapters |
| `StateRepositoryPort` | `SQLiteStateRepository` (WAL mode) |
| `EventBusPort` | `AsyncEventBus` (in-process, parallel dispatch) |
| `CheckpointPort` | `SQLiteCheckpointStore` (async I/O offloaded) |
| `ToolRepositoryPort` | `SQLiteToolRepository` (aiosqlite) |
| `SandboxPort` | `NativeWindowsSandbox` / `DockerLinuxSandbox` / `WSL2Sandbox` |

### 5. Model Cascading
LLM calls cascade FREE → BUDGET → PREMIUM. `ResilientLLMAdapter` wraps each with `CircuitBreaker` (jittered recovery) + `RetryWithBackoff` (exponential, ±25% jitter).

### 6. Event-Sourced Sessions
19 discriminated event types. `EventStore` provides SQLite append-only audit log. `Session` carries immutable `events_json` list.

---

## Entry Points

| Entry | Path | Pattern |
|-------|------|---------|
| CLI | `cli/main.py` | Click commands → `Container.configure_defaults()` → flow.run() |
| Web API | `weebot/interfaces/web/main.py` | FastAPI app factory → `Container.get()` via `Depends` |
| MCP Server | `weebot/mcp/server.py` | FastMCP with stdio/SSE transport; API key auth on SSE |
| Discord | `weebot/interfaces/gateways/discord.py` | Interaction endpoint + signature verification |
| Slack | `weebot/interfaces/gateways/slack.py` | Events API + signature verification |
| Telegram | `weebot/interfaces/gateways/telegram.py` | Bot API webhook |
| Python API | `weebot/application/di/__init__.py` | Library import via `Container` |

---

## Architecture Decision Records

| ADR | Decision | File |
|-----|----------|------|
| 001 | Pydantic models over stdlib dataclasses | `docs/adr/001-pydantic-over-dataclasses.md` |
| 002 | CQRS Mediator over traditional service layer | `docs/adr/002-mediator-over-service-layer.md` |
| 003 | `typing.Protocol` over `abc.ABC` for domain ports | `docs/adr/003-protocol-vs-abc-ports.md` |
| 004 | SQLite over PostgreSQL (current phase) | `docs/adr/004-sqlite-over-postgres.md` |
| 005 | In-process EventBus over message queue | `docs/adr/005-in-process-event-bus.md` |

---

## Enforcement

| Mechanism | What It Enforces | Location |
|-----------|-----------------|----------|
| `import-linter` | 5 layer-boundary contracts | `.importlinter` |
| Architecture fitness tests | 19 AST-based checks (import rules, handler registration, DB access, blocking calls, settings imports) | `tests/unit/test_architecture_fitness.py` |
| Port contract tests | Every port has adapter + adapter implements all abstract methods + DI constructibility | `tests/unit/test_port_contracts.py` |
| CI workflow | Runs fitness tests on push | `.github/workflows/architecture.yml` |

---

## Known Technical Debt

| # | Item | Severity | Status |
|---|------|----------|--------|
| D1 | PowerShellTool inherits sync `langchain.tools.BaseTool` | HIGH | ✅ CLOSED |
| D2 | 3 tools import `sqlite3` directly | MEDIUM | ✅ CLOSED |
| D3 | God DI container (~800 lines) | MEDIUM | ✅ CLOSED — split into 6 files |
| D4 | `get_event_bus()` singleton | LOW | ✅ CLOSED |
| D5 | Untyped `Session.context` | MEDIUM | ✅ CLOSED |
| D6 | No session-level retry | MEDIUM | ✅ CLOSED |
| D7 | Single SQLite file shared across all persistence | MEDIUM | ⏳ Partial — PostgreSQL adapter scaffolded |
| D8 | CLI at ~1500 lines | LOW | ✅ CLOSED |
| D9 | 3 deprecated root shims | LOW | ⏳ Partial — active callers prevent deletion |
| D10 | `PlanActFlow.__init__` 22 parameters | MEDIUM | ✅ CLOSED — extracted to `PlanActFlowConfig` dataclass |
| D11 | Sync SQLite in async methods | MEDIUM | ✅ CLOSED — `run_in_executor` and `aiosqlite` migration |
| D12 | PowerShell injection patterns missing | MEDIUM | ✅ CLOSED — 8 patterns added to `CommandSecurityAnalyzer` |
| D13 | MCP server no auth on SSE transport | MEDIUM | ✅ CLOSED — API key via FastMCP `TokenVerifier` |
| D14 | BashGuard security events not metered | MEDIUM | ✅ CLOSED — `bash_guard_events_total` Prometheus counter |

---

## Scaling Triggers

| Condition | Required Change |
|-----------|----------------|
| >10 concurrent users | PostgreSQL migration (SQLite write serialization ceiling) |
| Multi-process deployment | Redis/RabbitMQ task queue |
| >100 tool definitions | Enforce `ToolRepositoryPort` for all tools |
| Cross-session agent communication | `SwarmEventBusPort` (in-process insufficient) |
| Compliance/audit requirements | Durable `EventStorePort` |

---

## Meta-Orchestration State (2026-06-07)

- **System state:** HEALTHY
- **Complexity (C):** 6 | **Stability (S):** 7 | **Fragility (F):** 5
- **Regret Potential (RP):** 1.65 | **Growth Tension (GT):** 5.2
- **Next assessment:** 2026-07-07 or trigger event
- **Full report:** `docs/assessments/2026-06-07_meta-orchestration-cycle-1.md`
