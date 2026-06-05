# ARCHITECTURE.md — weebot AI Orchestrator

**Last updated:** 2025-07-18  
**Architecture score:** 8.5/10 (Phase A complete — see debt table below)  
**Last audit:** ARCH-AUDIT-V2 (2025-07-18) → Phase A debt closure  
**Maturity:** Early Production  
**Paradigm:** Clean Architecture (Hexagonal Ports & Adapters) + CQRS Mediator + State-Machine Flows

---

## Layer Map

```
Interfaces (CLI / Web / MCP)
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

**[VERIFIED]** Layer boundaries enforced by `.importlinter` (5 contracts) and `tests/unit/test_architecture_fitness.py` (AST-based). Domain purity confirmed: zero outer-layer imports across 36 domain `.py` files.

---

## Package Structure (current)

```
weebot/
├── domain/                         # Enterprise business logic
│   ├── models/                     # Pydantic entities (Plan, Step, Session, Event, Skill, etc.)
│   ├── ports.py                    # 5 Protocol ports (IModelProvider, IRepository, INotifier, ITool, EventPublisher)
│   ├── services/                   # Domain services (session_memory, working_memory, human_interaction)
│   ├── exceptions.py               # Exception hierarchy
│   └── legacy_models.py            # Frozen legacy types
│
├── application/                    # Use cases & orchestration
│   ├── di.py                       # Container — single composition root (~800 lines)
│   ├── ports/                      # 32 ABC port interfaces (llm_port, state_repo_port, sandbox_port, etc.)
│   ├── flows/                      # State-machine flows
│   │   ├── plan_act_flow.py        # Primary Plan→Act→Critique→Summarize loop
│   │   ├── chat_flow.py
│   │   ├── skill_opt_flow.py       # Skill optimization (batch training)
│   │   └── states/                 # Per-state classes (planning, executing, critiquing, etc.)
│   ├── agents/                     # LLM-calling agents (PlannerAgent, ExecutorAgent, ChatAgent, etc.)
│   ├── cqrs/                       # CQRS with Mediator pipeline
│   │   ├── mediator.py             # Dispatcher (behaviors extracted to behaviors/)
│   │   ├── commands.py             # Command models
│   │   ├── queries.py              # Query models
│   │   ├── handlers.py             # Command + query handlers
│   │   └── behaviors/              # Pipeline behaviors (logging, validation, validation_gate, save_policy, telemetry)
│   ├── services/                   # ~55 application services (task_runner, memory_compactor, plan_critic, etc.)
│   └── skills/                     # Skill registry + built-in skills
│
├── infrastructure/                 # Adapter implementations
│   ├── adapters/
│   │   ├── llm/                    # AnthropicAdapter, OpenAIAdapter, DeepSeekAdapter, OpenRouterAdapter, ResilientLLMAdapter
│   │   ├── speech/                 # WhisperSpeechAdapter
│   │   └── ...                     # config_adapter, steering_adapter, windows_desktop, rtk_provider, gitnexus_provider
│   ├── persistence/                # SQLiteStateRepository, SQLiteKnowledgeGraph, FileSystemMemory, etc.
│   ├── browser/                    # PlaywrightAdapter, session_manager, content_extractor
│   ├── sandbox/                    # DockerLinuxSandbox, NativeWindowsSandbox, WSL2Sandbox (factory-dispatched)
│   ├── mcp/                        # MCP client manager + tool bridge
│   ├── notifications/              # TelegramAdapter, WindowsToastAdapter
│   ├── event_bus.py                # AsyncEventBus (implements EventBusPort)
│   └── events/                     # EventStore, EventBrokerAdapter, event_reconstructor
│
├── interfaces/                     # Entry points
│   ├── web/                        # FastAPI app factory + routers
│   ├── cli/                        # CLI support utilities
│   ├── sse/                        # Server-Sent Events streaming
│   └── gateways/                   # Discord bot gateway
│
├── core/                           # Cross-cutting concerns (26 modules)
│   ├── bash_guard.py               # 4-tier shell safety analysis
│   ├── circuit_breaker.py          # CLOSED/OPEN/HALF_OPEN state machine
│   ├── safety.py                   # SafetyChecker (LLM-powered plan B for critical ops)
│   ├── approval_policy.py          # DENY/ALWAYS_ASK/AUTO_APPROVE rules
│   ├── model_cascade.py            # FREE → BUDGET → PREMIUM cost optimization
│   ├── adaptive_concurrency.py     # Dynamic worker scaling
│   ├── workflow_orchestrator.py    # DAG-based multi-agent execution
│   ├── dependency_graph.py         # DAG validation + topological sort
│   └── agent_context.py            # Shared context for agent hierarchies
│
├── tools/                          # Agent tool implementations
│   ├── bash_tool.py                # Shell execution via SandboxPort
│   ├── python_tool.py              # Python execution via SandboxPort
│   ├── powershell_tool.py          # ⚠️ Powershell (inherits langchain BaseTool — see debt)
│   ├── browser_tool.py             # Browser automation
│   ├── persistent_memory.py        # Persistent memory via MemoryPort
│   ├── knowledge_tool.py           # ⚠️ Direct sqlite3 import (see debt)
│   ├── product_tool.py             # ⚠️ Direct sqlite3 import (see debt)
│   ├── video_ingest_tool.py        # ⚠️ Direct sqlite3 import (see debt)
│   └── ...
│
├── templates/                      # Jinja2 template engine + YAML templates
├── skills/                         # Built-in skill manifests + prompts
├── mcp/                            # MCP server + resources
├── integrations/                   # Obsidian, Zotero
├── scheduling/                     # NL-based cron scheduler
├── config/                         # Settings, constants, tool_config, model_registry
│   ├── settings.py                 # WeebotSettings (pydantic-settings)
│   └── constants.py                # DEFAULT_MAX_FLOW_ITERATIONS (50), etc.
│
cli/                                # Click CLI entry module
├── main.py                         # ~1500 lines (growing — see debt)
└── commands/                       # CLI command groups
tests/
├── unit/                           # Pure domain + application tests
├── integration/                    # Adapter tests
├── e2e/                            # End-to-end tests
└── unit/test_architecture_fitness.py  # AST-based boundary enforcement
docs/
├── adr/                            # 5 Architecture Decision Records
├── plans/                          # Design docs + remediation plans
└── ARCHITECTURE_AUDIT*.md          # Historical audit reports
```

---

## Key Design Patterns

### 1. Dependency Injection (Container)
All adapters are wired at the composition root (`weebot/application/di.py`). `Container` is a `@dataclass` with lazy factories. Ports are registered with concrete adapter factories; consumers call `Container.get(PortType)`.

```python
container = Container()
container.configure_defaults()
llm = container.get(LLMPort)           # → ResilientLLMAdapter
repo = container.get(StateRepositoryPort)  # → SQLiteStateRepository
```

### 2. CQRS + Mediator Pipeline
All state mutations go through `Mediator.send(command)` → ordered pipeline behaviors → handler.

```
Mediator.send(CreatePlanCommand(...))
  → LoggingBehavior       (logs command)
  → TelemetryBehavior     (records metrics)
  → SavePolicyBehavior    (decides save strategy)
  → CreatePlanHandler     (business logic + persistence)
  → CommandResult[T]
```

Behaviors are composable and order-independent. Each `SkillOptFlow` gets a **scoped** mediator (not the shared singleton) to prevent duplicate behavior accumulation [di.py:747-750].

### 3. State-Machine Flows
`PlanActFlow` transitions through discrete states, each a separate class implementing `FlowState`:

```
Idle → Planning → Executing → Critiquing → Summarizing → Updating → Completed
         ↑                                                      │
         └──────────────────────────────────────────────────────┘
                            (re-plan on failure)
```

### 4. Port/Adapter (Hexagonal)
Every external resource is behind an ABC port in `application/ports/`. Infrastructure adapters implement those ports. The domain layer defines lightweight `Protocol` ports for its own boundaries.

| Application Port | Infrastructure Adapter |
|-----------------|----------------------|
| `LLMPort` | `ResilientLLMAdapter` wrapping provider-specific adapters |
| `StateRepositoryPort` | `SQLiteStateRepository` (WAL mode) |
| `EventBusPort` | `AsyncEventBus` (in-process) |
| `EventStorePort` | `EventStore` (SQLite append-only log) |
| `SandboxPort` | `NativeWindowsSandbox` / `DockerLinuxSandbox` / `WSL2Sandbox` |
| `MemoryPort` | `FileSystemMemoryAdapter` |

### 5. Model Cascading
LLM calls cascade through cost tiers: FREE → BUDGET → PREMIUM. `ResilientLLMAdapter` wraps each with `CascadeCircuitBreaker` + `RetryWithBackoff` (jittered exponential backoff).

### 6. Event-Sourced Sessions
`Session` model carries an immutable `events_json` list. 11 discriminated event types (`PlanEvent`, `StepEvent`, `ToolEvent`, `ErrorEvent`, etc.). `EventStorePort` provides an append-only audit log.

---

## Entry Points

| Entry | Path | Pattern |
|-------|------|---------|
| CLI | `cli/main.py` | Click commands → `Container.configure_defaults()` → flow.run() |
| Web API | `weebot/interfaces/web/main.py` | FastAPI app factory → `Container.get()` via `Depends` |
| MCP Server | `run_mcp.py` → `weebot/mcp/server.py` | Model Context Protocol |
| Python API | `weebot/application/di.py` → `build_agent_runner()` | Library import |

---

## Architecture Decision Records

| ADR | Decision | File |
|-----|----------|------|
| 001 | Pydantic models over stdlib dataclasses | `docs/adr/001-pydantic-over-dataclasses.md` |
| 002 | CQRS Mediator over traditional service layer | `docs/adr/002-mediator-over-service-layer.md` |
| 003 | `typing.Protocol` over `abc.ABC` for ports | `docs/adr/003-protocol-vs-abc-ports.md` |
| 004 | SQLite over PostgreSQL (current phase) | `docs/adr/004-sqlite-over-postgres.md` |
| 005 | In-process EventBus over message queue | `docs/adr/005-in-process-event-bus.md` |

---

## Enforcement

| Mechanism | What It Enforces | Location |
|-----------|-----------------|----------|
| `import-linter` | 5 layer-boundary contracts (domain-purity, tools-no-db, infra-no-app-services, interfaces-no-infra) | `.importlinter` |
| Architecture fitness tests | AST-based boundary checks, flat-file elimination, handler registration completeness | `tests/unit/test_architecture_fitness.py` |
| CI workflow | Runs `lint-imports` on push | `.github/workflows/architecture.yml` |

---

## Known Technical Debt

| # | Item | Severity | Status | Location | Plan Phase |
|---|------|----------|--------|----------|-----------|
| D1 | PowerShellTool inherits sync `langchain.tools.BaseTool` | HIGH | ✅ **CLOSED** — now uses `weebot.tools.base.BaseTool` + `SandboxPort` | A1 complete |
| D2 | 3 tools import `sqlite3` directly (bypass `ToolRepositoryPort`) | MEDIUM | ✅ **CLOSED** — all 3 tools now inject `ToolRepositoryPort` | A2 complete |
| D3 | God DI container (~800 lines, 17+ concerns) | MEDIUM | 🔴 Pending | Split into `di/` subpackage (R4) |
| D4 | `get_event_bus()` singleton | LOW | ✅ **CLOSED** — removed from `event_bus.py`, no runtime callers | A3 complete |
| D5 | Untyped `Session.context` | MEDIUM | ✅ **CLOSED** — already typed as `SessionContext(BaseModel)` with facts eviction | Pre-existing |
| D6 | No session-level retry when all LLM tiers fail | MEDIUM | 🔴 Pending | Add `max_session_retries` with backoff (R6) |
| D7 | Single SQLite file shared across all persistence | MEDIUM | 🔴 Pending | Split per-domain; PostgreSQL for multi-user |
| D8 | CLI at ~1500 lines, not split by concern | LOW | ⏳ Partial — `flow` group extracted to `cli/commands/flow.py` (1518 lines) | A5 partial |
| D9 | 3 deprecated root shims still present | LOW | ⏳ Partial — have active callers; can't delete yet | A3 partial |

---

## Scaling Triggers

| Condition | Required Change |
|-----------|----------------|
| >10 concurrent users on same deployment | PostgreSQL migration (SQLite write serialization ceiling) |
| Multi-process deployment | Redis/RabbitMQ task queue (replace `asyncio.PriorityQueue`) |
| >100 tool definitions | Enforce `ToolRepositoryPort` for all tools; eliminate direct sqlite3 |
| Cross-session agent communication | Implement `SwarmEventBusPort` (in-process `AsyncEventBus` insufficient) |
| Compliance/audit requirements | Guarantee durable `EventStorePort` (currently in-memory + SQLite) |

---

## Phase A Debt Closure (2025-07-18)

Phase A of the 7.8 → 9.0 plan closed 5 of 9 debt items, raising the score to ~8.5/10.

| Item | Severity | Status |
|------|----------|--------|
| PowerShellTool (D1) | HIGH | ✅ Rewritten — no langchain, routes through `SandboxPort` |
| 3 sqlite3 tools (D2) | MEDIUM | ✅ All inject `ToolRepositoryPort` via DI |
| `get_event_bus()` (D4) | LOW | ✅ Removed; zero runtime callers |
| `SessionContext` typing (D5) | MEDIUM | ✅ Already typed; no work needed |
| CLI split (D8) | LOW | ⏳ `flow` group extracted; 1518 lines remain |
| Root shims (D9) | LOW | ⏳ Active callers prevent deletion yet |

Remaining Phase B–D items: DI container split (D3), session retry (D6), PostgreSQL (D7).

Full plan: `docs/plans/ARCHITECTURE_9_PLAN.md`.
