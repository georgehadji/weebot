# Architecture Review

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21  
**Architecture Style:** Clean Architecture (Hexagonal) with CQRS + Event Sourcing

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INTERFACES LAYER                             │
│  FastAPI CLI  MCP Server  Discord/TG/Slack  WebSocket              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ depends on
┌──────────────────────────▼──────────────────────────────────────────┐
│                     APPLICATION LAYER                                │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────┐                   │
│  │   Flows      │  │  Agents  │  │   Services   │                   │
│  │  PlanActFlow │  │ Planner  │  │ MemCompactor │                   │
│  │  ChatFlow    │  │ Executor │  │ PlanCritic   │                   │
│  │  HyperFlow   │  │ Hyper    │  │ TruthBinder  │                   │
│  └──────┬───────┘  └────┬─────┘  └──────┬───────┘                   │
│         │               │               │                            │
│  ┌──────▼───────────────▼───────────────▼──────┐                    │
│  │               PORTS (interfaces)            │                    │
│  │  LLMPort  SandboxPort  StateRepoPort  ...  │                    │
│  └──────────────────────┬─────────────────────┘                    │
│  ┌──────────────────────▼─────────────────────┐                    │
│  │          DI Container (wiring)              │                    │
│  └──────────────────────┬─────────────────────┘                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ implements
┌──────────────────────────▼──────────────────────────────────────────┐
│                    INFRASTRUCTURE LAYER                              │
│  LLM Adapters  SQLite Pool  EventStore  Sandbox  Cache  Browser    │
│  Security Validators  Prometheus  OpenTelemetry  MCP Bridge        │
└─────────────────────────────────────────────────────────────────────┘
                           │ pure
┌──────────────────────────▼──────────────────────────────────────────┐
│                       DOMAIN LAYER                                  │
│  Session  Plan  Step  Event  BehavioralRule  Opportunity           │
│  Exceptions: SecurityException, PathTraversalError                 │
│  (zero infrastructure imports)                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Architecture Health

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Layer Separation** | 8/10 | Clean boundaries. Domain is pure. Port/adapter pattern used consistently |
| **Dependency Inversion** | 7/10 | Mostly good, but PlanActFlow creates Container instances (violation) |
| **Testability** | 7/10 | Ports enable mocking, but some components hard to test without Container |
| **Cohesion** | 6/10 | PlanActFlow is a God object (30+ constructor params) |
| **Complexity** | 6/10 | Event storage split across two systems with different schemas |
| **Scalability** | 5/10 | Single-process, synchronous event store, no backpressure |

---

## Previously Identified Issues (Resolved)

| Issue | File | Resolution |
|-------|------|------------|
| Module-level variable corruption | `resilient_adapter.py` | Removed stray `LLMCache=None` / `CacheKey=None` |
| CORS wildcard | `web/main.py` | Replaced with explicit allowlist |
| WebSocket auth bypass | `web/main.py` | Added token validation |
| Self-instantiated Containers | `bash_tool.py`, `python_tool.py` | Wrapped with try/except + RuntimeError |
| Unbounded session list query | `sessions.py` | Added SQL-level pagination |
| Full event deserialization on list | `sqlite_state_repo.py` | Added `load_events=False` |
| FTS5 write amplification | `sqlite_state_repo.py` | Incremental indexing via `_fts5_indexed` tracker |
| HTML injection regex bug | `security_validators.py` | Fixed `[\\s\\S]` -> `[\s\S]` in `r""` string |

---

## Remaining Architecture Issues

### ARCH-001: Dual Event Storage Systems

**Files:** `weebot/infrastructure/event_store.py` (sync sqlite3) + `sqlite_state_repo.py` (async aiosqlite)

**Issue:** Events are stored in two incompatible databases under incompatible schemas. The EventStore tracks cost data; the StateRepo tracks session state. They cannot be queried together.

**Recommendation:** Merge into a single database with shared connection pool.

### ARCH-002: PlanActFlow God Object

**File:** `plan_act_flow.py` (30+ constructor params, 350-line init)

**Issue:** Single class handling state machine execution, event emission, persistence, checkpointing, model selection, truth binding, credential sanitization, domain event publishing, tracing, hooks.

**Recommendation:** Extract `EventEmitter`, `FlowPersistence`, `ModelSelector` collaborators.

### ARCH-003: No Schema Migrations

**Issue:** All tables use `CREATE TABLE IF NOT EXISTS`. Schema changes require manual database deletion.

**Recommendation:** Use Alembic (already in `requirements.txt`).

### ARCH-004: Circuit Breaker In-Memory Only

**Issue:** Circuit breaker state lost on restart, causing initial burst of failures to failing models.

**Recommendation:** Persist breaker state to SQLite.

---

## Dependency Flow Analysis

```
Expected:  Interfaces → Application → Domain ← Infrastructure
                                      ↑
                              (ports define contracts)

Verified violations:
- PlanActFlow._get_persistence_adapter() creates Container()       [Application → Container]
- PlanActFlow._get_tracing_port() creates Container()             [Application → Container]
- BashTool.__init__ creates Container() when sandbox=None         [Tool → Container]
- PythonExecuteTool.__init__ creates Container() when sandbox=None [Tool → Container]
```

All four violations were mitigated in the last commit (wrapped with try/except + RuntimeError), but the root cause — components reaching outside their layer for dependencies — remains. The proper fix is full constructor injection through DI.
