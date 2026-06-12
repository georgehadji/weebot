# Architecture Review

**Codebase:** Weebot AI Agent Framework  
**Assessment Date:** 2025-07-21  
**Architecture Style:** Clean Architecture (Hexagonal) with CQRS

---

## Overall Architecture Assessment

The project demonstrates **strong architectural intent** with proper layering:
- Domain layer is pure (no external dependencies)
- Port/adapter pattern is consistently applied
- DI container centralizes wiring
- CQRS with mediator pattern for command/query separation

However, several structural issues undermine the architecture's benefits:

---

## Finding ARCH-001: Module-Level Variable Corruption in Resilient Adapter

**Severity:** CRITICAL (introduces silent bugs)  
**Status:** VERIFIED  
**Location:** `weebot/infrastructure/adapters/llm/resilient_adapter.py` (lines 30-35)

### Evidence
```python
def _sanitize_error(exc: BaseException) -> None:
    """Redact credential patterns from exception messages in-place."""
    msg = str(exc)
    for pattern, replacement in _CREDENTIAL_REDACTIONS:
        msg = pattern.sub(replacement, msg)
    if msg != str(exc):
        try:
            exc.args = (msg,) + exc.args[1:]
        except (AttributeError, TypeError):
            pass
    LLMCache = None   # <--- INDENTATION BUG: executes at function level, not inside try
    CacheKey = None   # <--- Overwrites module-level imports on every call
```

### Root Cause
These two lines are indented inside the function body but OUTSIDE the `if` block and `try` block where they logically belong. They execute unconditionally every time `_sanitize_error` is called, setting the module-level `LLMCache` and `CacheKey` to `None`.

### Impact
- After the first LLM error occurs, ALL subsequent cache operations silently fail
- The `CACHE_AVAILABLE` flag at module top still reads `True` (set during import)
- This creates a subtle degradation: caching appears configured but does nothing
- Performance degrades progressively as more requests bypass cache

### Correct Fix
These lines should not exist in `_sanitize_error` at all. They appear to be a copy-paste artifact from the try/except import block at the top of the file. Remove them entirely.

---

## Finding ARCH-002: PlanActFlow God Object

**Severity:** HIGH  
**Status:** VERIFIED  
**Location:** `weebot/application/flows/plan_act_flow.py`

### Evidence
The `PlanActFlow.__init__` constructor accepts **30+ parameters** and stores them all as instance variables. The class is responsible for:
- State machine transitions
- Event emission
- Session persistence  
- Checkpoint management
- Plan history (undo/redo)
- Model selection
- Truth binding
- Credential sanitization
- Domain event publishing
- Tracing
- Hook execution

### Impact
- Violates Single Responsibility Principle
- Makes unit testing require mocking 10+ dependencies
- High cognitive load for new contributors
- Changes to any concern risk breaking unrelated functionality

### Recommended Decomposition
1. Extract `EventEmitter` — handles event publishing, sanitization, truth-binding
2. Extract `FlowPersistence` — handles checkpoint saving, session persistence
3. Extract `ModelSelector` — handles context-aware model switching
4. Keep `PlanActFlow` as a thin orchestrator that delegates to these collaborators

---

## Finding ARCH-003: DI Container Creates New Containers Internally

**Severity:** MEDIUM  
**Status:** VERIFIED  
**Location:** `weebot/application/flows/plan_act_flow.py` (line ~320, ~340)

### Evidence
```python
def _get_persistence_adapter(self):
    if self._persistence_adapter is None:
        from weebot.application.di import Container
        c = Container()  # <--- NEW container, not the app-level singleton
        try:
            self._persistence_adapter = c.get("session_persistence")
        except KeyError:
            return None
    return self._persistence_adapter

def _get_tracing_port(self):
    if self._tracing_port is None:
        from weebot.application.di import Container
        from weebot.application.ports.tracing_port import TracingPort
        c = Container()
        c.configure_defaults()  # <--- Reconfigures from scratch
        self._tracing_port = c.get(TracingPort)
    return self._tracing_port
```

### Root Cause
The flow lazily resolves ports by creating a FRESH Container rather than using the application-level container that was used to create the flow itself.

### Impact
- Multiple database connections created (one per Container)
- Different singleton instances for the same port type
- Tracing adapter created fresh = loses accumulated state
- Memory leak from orphaned connection pools

### Remediation
Pass the container (or the needed ports) via constructor injection. The flow should never instantiate its own Container.

---

## Finding ARCH-004: Circular Dependency Pattern in DI

**Severity:** MEDIUM  
**Status:** STRONG HYPOTHESIS  
**Location:** `weebot/application/di/__init__.py`

### Evidence
The Container's factory methods import from modules that themselves import from the Container:
- `_create_sub_agent_factory` imports `PlanActFlow`
- `PlanActFlow` lazily imports `Container`
- `BashTool.__init__` creates a new `Container()` when no sandbox is injected

### Impact
- Import-time circular dependencies are avoided by lazy imports, but runtime circular resolution is possible
- Test isolation is difficult — any tool creation pulls in the full DI graph
- Memory usage: creating BashTool without DI creates a full Container singleton chain

---

## Finding ARCH-005: Event Bus Fire-and-Forget Without Backpressure

**Severity:** MEDIUM  
**Status:** STRONG HYPOTHESIS  
**Location:** `weebot/infrastructure/event_bus.py`, `weebot/application/flows/plan_act_flow.py`

### Evidence
```python
# In PlanActFlow._emit():
if self._event_bus:
    await self._event_bus.publish(event)
    await self._emit_domain_event(event)
```

The event bus publishes to all subscribers. If a subscriber is slow (e.g., SSE broadcast, WebSocket push, disk persistence), the flow blocks until all subscribers complete. There is no:
- Subscriber timeout
- Backpressure mechanism
- Dead letter queue for failed deliveries
- Circuit breaker on slow subscribers

### Impact
- A slow WebSocket client can block the entire Plan-Act flow
- A crashed subscriber causes event loss
- No visibility into subscriber lag

---

## Finding ARCH-006: Two Separate Event Storage Systems

**Severity:** LOW (architectural debt, not a bug)  
**Status:** VERIFIED  
**Location:** `weebot/infrastructure/event_store.py` vs `weebot/infrastructure/persistence/sqlite_state_repo.py`

### Evidence
1. `EventStore` — synchronous sqlite3, stores events in `~/.weebot/events.db`
2. `SQLiteStateRepository` — async aiosqlite, stores events as JSON blob in sessions table

Both store event data but in incompatible formats, different databases, and with different schemas.

### Impact
- Event data is duplicated across two databases
- No single source of truth for "what happened in session X"
- FTS5 search only covers the state repo, not the event store
- Cost tracking is in the event store; session state is in the state repo

---

## Finding ARCH-007: Layer Violation — Infrastructure Imports in Core

**Severity:** LOW  
**Status:** VERIFIED  
**Location:** `weebot/core/bash_guard.py` (line 8)

### Evidence
```python
_bash_guard_hooks: Any = None

def set_bash_guard_hooks(registry: Any) -> None:
    global _bash_guard_hooks
    _bash_guard_hooks = registry
```

While not a direct import, the core layer uses a global mutable variable that is set by the infrastructure layer. The `BashTool` then references `_bash_guard_hooks` from within its execution flow. This is a soft layer violation — the core module has runtime coupling to infrastructure-provided behavior.

### Impact
- Testing bash_guard requires clearing/mocking the global
- Module-level state makes the code non-thread-safe if used from multiple event loops

---

## Dependency Flow Analysis

```
Expected:  Interfaces → Application → Domain ← Infrastructure
                                      ↑
                              (ports define contracts)
```

**Verified conformance:**
- Domain models have zero infrastructure imports ✅
- Ports are defined in `application/ports/` ✅
- Adapters in `infrastructure/` implement ports ✅
- CLI and Web in `interfaces/` only use application services ✅

**Violations found:**
- `PlanActFlow` creates `Container` instances (Application → DI → Infrastructure)
- `BashTool` creates `Container` when no sandbox injected (Tool → DI → Infrastructure)
- `_bash_guard_hooks` global creates hidden coupling (Core ← Infrastructure)

---

## Complexity Hotspots

| File | Cyclomatic Complexity | Lines | Concern |
|------|----------------------|-------|---------|
| `plan_act_flow.py` | Very High | ~350 | State machine + persistence + events |
| `di/__init__.py` | High | ~260 | All wiring in one place |
| `bash_tool.py` | High | ~200 | Multi-layer security + execution |
| `resilient_adapter.py` | Medium | ~200 | Retry + circuit breaker + cache |
| `sqlite_state_repo.py` | Medium | ~330 | CRUD + opportunities + FTS5 |

---

## Positive Architecture Decisions

1. **Port/Adapter pattern** consistently applied for testability
2. **CQRS with Mediator** enables clean command/query separation
3. **State machine pattern** in flows provides clear state transitions
4. **Behavioral rules YAML** keeps domain logic configurable
5. **Circuit breaker with jitter** prevents thundering herd
6. **WAL mode SQLite** with dedicated write connection is correct for the use case
7. **Credential sanitizer** in the event emission path prevents secret leakage to storage
