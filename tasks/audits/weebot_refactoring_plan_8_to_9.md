# REFACTORING PLAN: Architecture Score 8.0 → 9.5+

**Based on:** `tasks/audits/weebot_architecture_audit_v2_full.md` (2026-06-10)
**Current Score:** 8.0/10
**Target Score:** 9.5/10
**Estimated Effort:** 4 phases across 3 sprints

---

## SCORE GAP ANALYSIS

The 8.0 score reflects drift across 6 modules with MEDIUM findings. To reach 9.5+, every MEDIUM finding must be eliminated and most LOW findings resolved. The rubric:

| Score | Definition |
|-------|-----------|
| 8 | Minor drift in 1-2 modules, no critical violations |
| 9 | All layers correctly separated, patterns consistent, minor cosmetic drift only |
| 10 | All layers correctly separated, patterns consistent, observable, testable, scalable |

**Gap:** 1.5 points = 4 MEDIUM findings + 6 LOW findings + 2 enforcement gaps

### Finding → Score Impact Map

| Finding | Severity | Score Suppressor | Refactor Phase |
|---------|----------|-----------------|----------------|
| F-001: Dual event systems (EventBroker vs AsyncEventBus) | MEDIUM | -0.5 | Phase 1 |
| F-002: No backpressure on AsyncEventBus | MEDIUM | -0.3 | Phase 1 |
| F-003: Anemic domain model | MEDIUM | -0.3 | Phase 2 |
| F-004: PlanActFlow imports agents at module level | MEDIUM | -0.3 | Phase 1 |
| F-005: `core/agent.py` legacy layer leak | MEDIUM | -0.2 | Phase 1 |
| F-006: `tools/bash_tool.py` DI coupling | LOW | -0.1 | Phase 1 |
| F-007: `mcp/server.py` tool instantiation outside DI | LOW | -0.1 | Phase 1 |
| F-008: `EventStore` sync sqlite3 with `asyncio.to_thread` | LOW | -0.1 | Phase 3 |
| F-009: `bash_security.py` dead LLM code | LOW | -0.05 | Phase 1 |
| F-010: `AgentRunner` reaches into core internals | LOW | -0.1 | Phase 2 |
| F-011: PlanActFlowConfig 22-param complexity | LOW | -0.1 | Phase 2 |
| F-012: Legacy frozen modules in codebase | LOW | -0.1 | Phase 3 |
| **Total** | | **-2.35** | |

Addressing all findings: 8.0 + 2.35 = **10.35 → capped at 9.5** (remaining gap = enforcement maturity)

---

## PHASE 1: EVENT SYSTEM CONSOLIDATION + CRITICAL COUPLING FIXES

**Target:** Eliminate F-001, F-002, F-004, F-005, F-006, F-007, F-009
**Score Impact:** 8.0 → 8.8 (+0.8)
**Effort:** 1 sprint (5-7 days)
**Risk:** MEDIUM (touches core event infrastructure)

### 1A. Add Backpressure to AsyncEventBus [F-002]

**File:** `weebot/infrastructure/event_bus.py`

**Current state:**
```python
async def publish(self, event: AgentEvent) -> None:
    async with self._lock:
        handlers = list(self._handlers)
    if not handlers:
        return
    results = await asyncio.gather(
        *[self._safe_call(h, event) for h in handlers],
        return_exceptions=True,
    )
```

**Problem:** No concurrency limit. A slow handler blocks all others. No retry on failure.

**Change:**
```python
class AsyncEventBus(EventBusPort):
    def __init__(self, max_concurrent_handlers: int = 10, max_retries: int = 2):
        self._handlers: List[EventHandler] = []
        self._domain_handlers: List[DomainEventHandler] = []
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)
        self._max_retries = max_retries

    async def publish(self, event: AgentEvent) -> None:
        # Prometheus counter (existing)
        try:
            _get_metrics().events_published_total.labels(
                event_type=getattr(event, "type", "unknown")
            ).inc()
        except Exception:
            pass

        async with self._lock:
            handlers = list(self._handlers)
        if not handlers:
            return

        results = await asyncio.gather(
            *[self._safe_call_with_retry(h, event) for h in handlers],
            return_exceptions=True,
        )
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.exception("Event handler %s failed after retries", handlers[idx])

    async def _safe_call_with_retry(self, handler: EventHandler, event: AgentEvent) -> None:
        """Execute handler with semaphore-bounded concurrency and retry."""
        async with self._semaphore:
            last_exc = None
            for attempt in range(self._max_retries + 1):
                try:
                    await handler(event)
                    return
                except Exception as exc:
                    last_exc = exc
                    if attempt < self._max_retries:
                        import asyncio as _aio
                        await _aio.sleep(0.1 * (2 ** attempt))  # exponential backoff
            raise last_exc  # type: ignore[misc]
```

**Impact:** Eliminates silent event loss. Bounded concurrency prevents handler starvation.

**Validation:**
- `tests/unit/test_event_bus_backpressure.py` (NEW) — test that slow handlers don't block fast ones
- Existing `tests/integration/test_event_bridge_contract.py` must still pass

---

### 1B. Bridge AgentContext to EventBusPort [F-001]

**Current state:** Two parallel event systems:
- `core/agent_context.py:EventBroker` — in-memory pub/sub with retry, bounded history (1000), tag index
- `infrastructure/event_bus.py:AsyncEventBus` — in-memory pub/sub, no retry, no bounded history

**Strategy (CORRECTED):** Do NOT make `EventBroker` delegate to `AsyncEventBus`. These serve different purposes:
- `EventBroker` = agent-to-agent coordination (typed `ContextEvent` with event_type, agent_id, data)
- `AsyncEventBus` = system-wide event distribution (Pydantic `AgentEvent` models)

Instead: (1) Add retry+backpressure to `AsyncEventBus` (done in 1A), (2) Bridge `AgentContext.publish_event()` to use `EventBusPort` when available, falling back to `EventBroker` for backward compat, (3) Deprecate `EventBroker` as the primary event channel.

**File: `weebot/core/agent_context.py`** — Update `publish_event` method:

```python
async def publish_event(
    self,
    event_type: str,
    data: Optional[Dict[str, Any]] = None
) -> bool:
    """Publish an event. Uses EventPublisher bridge when available,
    falls back to in-memory EventBroker for backward compatibility.
    """
    # Always record in local history for tag-based queries
    event = ContextEvent(
        event_type=event_type,
        agent_id=self.agent_id,
        data=data or {}
    )
    if len(self.event_broker._event_history) >= self.event_broker.MAX_HISTORY_SIZE:
        self.event_broker._event_history.pop(0)
    self.event_broker._event_history.append(event)
    self.event_broker._tag_index[event.event_type].append(event)
    self.event_broker._tag_index[f"agent_id:{event.agent_id}"].append(event)

    # Bridge to system-wide EventBusPort when available
    if self.event_publisher:
        from weebot.domain.models.event import MessageEvent
        agent_event = MessageEvent(
            role="assistant",
            message=f"[{event_type}] {self.agent_id}: {data}"
        )
        try:
            await self.event_publisher.publish(agent_event)
        except Exception as exc:
            _log.warning("EventBusPort bridge failed: %s", exc)
            self.event_broker._dropped_events += 1
            return False

    self.activity_stream.push(
        self.orchestrator_id, "event",
        f"{self.agent_id} published {event_type}"
    )
    return True
```

**File: `weebot/infrastructure/events/broker_adapter.py`** — Keep as-is for now. The bridge serves the correct purpose of connecting `EventBroker`-style calls to `AsyncEventBus`. Add deprecation notice.

**Callers to update:**
- `core/workflow_orchestrator.py` — pass `EventPublisher` protocol to `AgentContext` (already supported)
- `core/circuit_breaker.py` — no change needed (uses EventBroker directly, which is fine for circuit breaker events)
- `application/di/__init__.py` — ensure `EventPublisher` is wired to `AgentContext` instances

**What NOT to do:**
- Do NOT make `EventBroker` import `AsyncEventBus` (would violate core→infrastructure boundary)
- Do NOT wrap `ContextEvent` into `AgentEvent` (loses type semantics)
- Do NOT remove `EventBroker` entirely (still needed for agent-to-agent tag queries)

**Validation:**
- `tests/integration/test_event_bridge_contract.py` — must pass
- `tests/unit/test_agent_context.py` — must pass
- `tests/unit/test_event_broker_resilience.py` — must pass
- `tests/unit/test_architecture_fitness.py::test_domain_has_no_outer_imports` — must still pass (core has no infra imports)

---

### 1C. Remove Module-Level Agent Imports from PlanActFlow [F-004]

**File:** `weebot/application/flows/plan_act_flow.py`

**Current state (lines 9-10):**
```python
from weebot.application.agents.executor import ExecutorAgent
from weebot.application.agents.planner import PlannerAgent
```

**Problem:** Flow layer imports agent implementations at module level, coupling flows to specific agents.

**Change:** Move to lazy imports inside `__init__`:

```python
# Remove module-level imports of ExecutorAgent and PlannerAgent

# In __init__, after config normalization:
def __init__(self, config: PlanActFlowConfig = None, ...):
    # ... existing config normalization ...
    
    # Lazy imports — decouple flow from agent implementations
    from weebot.application.agents.planner import PlannerAgent
    from weebot.application.agents.executor import ExecutorAgent
    
    self._planner = PlannerAgent(...)
    self._executor = ExecutorAgent(...)
```

**Impact:** Flow layer no longer depends on agent implementations at import time.

**Also update:** `application/flows/states/planning.py` (line 49) — already uses lazy import, no change needed.

**Validation:**
- `tests/unit/test_architecture_fitness.py::test_no_direct_agent_calls_in_flow_states` — must pass
- All existing flow tests must pass

---

### 1D. Remove Legacy `core/agent.py` [F-005]

**File:** `weebot/core/agent.py` — `RecursiveWeebotAgent`

**Current state:** Imports `langchain_openai`, `PowerShellTool`, `BrowserTool`, `HeuristicRouter`, `SafetyChecker` directly. Bypasses DI entirely.

**Callers:**
- `tests/unit/test_recursive_agent_browser_async.py` — 1 test file imports it

**Action:**
1. Check if `RecursiveWeebotAgent` is referenced anywhere in production code (not tests)
2. If only test references: move test to `tests/unit/test_legacy_agent.py` with `@pytest.mark.skip("Legacy module — pending removal")`
3. Add `# DEPRECATED: Scheduled for removal. See architecture audit 2026-06-10.` header
4. Do NOT delete yet — other legacy modules may reference it indirectly

**Validation:**
- `tests/unit/test_architecture_fitness.py::test_domain_has_no_outer_imports` — unchanged
- Grep for `RecursiveWeebotAgent` — only in `core/agent.py` and test file

---

### 1E. Fix BashTool DI Coupling [F-006]

**File:** `weebot/tools/bash_tool.py`

**Current state (lines 64-70):**
```python
def __init__(self, sandbox: Optional[SandboxPort] = None):
    super().__init__()
    if sandbox is None:
        from weebot.application.di import Container
        container = Container()
        container.configure_defaults()
        sandbox = container.get(SandboxPort)
    self._sandbox = sandbox
```

**Problem:** Every `BashTool()` construction triggers full DI container initialization.

**Change:** Make sandbox required in the constructor, remove the lazy DI fallback:

```python
def __init__(self, sandbox: SandboxPort):
    """Initialise with a sandbox port instance (injected by DI).
    
    Args:
        sandbox: SandboxPort implementation for command execution.
            Must be provided by the caller (DI container or test fixture).
    """
    super().__init__()
    self._sandbox = sandbox
```

**Callers to update:**
- `weebot/application/di/__init__.py` (line 180, 248) — already injects via DI ✓
- `weebot/mcp/server.py` (line 182) — needs to inject sandbox
- `tests/unit/tools/test_bash_tool.py` — needs mock sandbox in fixtures
- `tests/integration/test_security_penetration.py` — needs mock sandbox

**Validation:**
- All `test_bash_tool.py` tests must pass with updated fixtures
- `mcp/server.py` must inject sandbox via DI

---

### 1F. Fix MCP Server Tool Instantiation [F-007]

**File:** `weebot/mcp/server.py`

**Current state (lines 103-106):**
```python
from weebot.tools.bash_tool import BashTool
from weebot.tools.python_tool import PythonExecuteTool
from weebot.tools.web_search import WebSearchTool
from weebot.tools.file_editor import StrReplaceEditorTool

_bash = BashTool()
_python = PythonExecuteTool()
_search = WebSearchTool()
_editor = StrReplaceEditorTool()
```

**Change:** Use DI container for tool construction:

```python
def _register_tools(self) -> None:
    mcp = self._mcp
    activity = self._activity

    # Resolve tools via DI container
    from weebot.application.di import Container
    from weebot.application.ports.sandbox_port import SandboxPort
    c = Container()
    c.configure_defaults()
    sandbox = c.get(SandboxPort)

    from weebot.tools.bash_tool import BashTool
    from weebot.tools.python_tool import PythonExecuteTool
    from weebot.tools.web_search import WebSearchTool
    from weebot.tools.file_editor import StrReplaceEditorTool

    _bash = BashTool(sandbox=sandbox)
    _python = PythonExecuteTool()
    _search = WebSearchTool()
    _editor = StrReplaceEditorTool()
```

**Validation:**
- `tests/unit/interfaces/test_mcp_server.py` — must pass
- MCP server startup must not crash

---

### 1G. Remove Dead LLM Security Code [F-009]

**File:** `weebot/tools/bash_security.py`

**Current state:** `_layer4_semantic_llm_analysis` method exists but is never called from the synchronous `analyze()` path.

**Action:** Remove the method entirely. It's dead code that references `ModelSelectionService` which is not imported.

```python
# DELETE: async def _layer4_semantic_llm_analysis(self, command: str) -> SecurityAssessment:
```

**Validation:**
- `tests/unit/tools/test_bash_security_falsifying.py` — must pass
- `tests/unit/test_architecture_fitness.py` — must pass

---

### Phase 1 Success Criteria

```bash
# Run all affected tests
pytest tests/unit/test_event_bus_backpressure.py tests/unit/test_agent_context.py tests/unit/test_event_broker_resilience.py tests/integration/test_event_bridge_contract.py tests/unit/test_architecture_fitness.py tests/unit/tools/test_bash_tool.py tests/unit/interfaces/test_mcp_server.py -v

# Run architecture fitness suite
pytest tests/unit/test_architecture_fitness.py -v

# Verify no new import violations
python -m importlinter --config .importlinter
```

**Expected Score After Phase 1:** 8.8/10

---

## PHASE 2: DOMAIN RICHNESS + FLOW DECOUPLING

**Target:** Eliminate F-003, F-010, F-011
**Score Impact:** 8.8 → 9.3 (+0.5)
**Effort:** 1 sprint (5-7 days)
**Risk:** LOW (internal refactoring, no behavior change)

### 2A. Enrich Domain Models [F-003]

**Goal:** Move business logic from application services into domain models where it naturally belongs. This reduces `PlanActFlowConfig` parameter count by encapsulating related concerns.

**File: `weebot/domain/models/session.py`** — Add domain behavior:

```python
class Session(BaseModel):
    # ... existing fields ...

    def apply_step_result(self, step_id: str, result: str, status: StepStatus) -> "Session":
        """Apply a step result to the session — domain logic, not service logic."""
        facts = dict(self.context.facts)
        facts[f"step_{step_id}_result"] = result
        facts[f"step_{step_id}_status"] = status.value
        new_ctx = self.context.model_copy(update={"facts": SessionContext._cap_facts_dict(facts)})
        return self.model_copy(update={"context": new_ctx})

    def is_stale(self, max_age_hours: float = 24.0) -> bool:
        """Check if session is stale — domain rule, not infrastructure."""
        import time
        if hasattr(self.updated_at, 'timestamp'):
            age_hours = (time.time() - self.updated_at.timestamp()) / 3600
            return age_hours > max_age_hours
        return False

    def effective_prompt(self, user_prompt: str) -> str:
        """Resolve effective prompt — enrich vague continuations with original task."""
        original = self.context.get("original_task", "")
        return ContinuationDetector.resolve_prompt(
            user_prompt=user_prompt,
            original_task=original,
            event_count=len(self.events),
        )
```

**File: `weebot/domain/models/plan.py`** — Add plan behavior:

```python
class Plan(BaseModel):
    # ... existing fields ...

    def current_step_description(self) -> str:
        """Return description of current step — domain query."""
        step = self.current_step
        return step.description if step else ""

    def progress_fraction(self) -> float:
        """Return completion fraction — domain metric."""
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        return completed / len(self.steps)
```

**Impact:** Reduces logic duplication in `PlanActFlow`, `MemoryCompactor`, `ContinuationDetector`. Domain models become self-describing.

**Validation:**
- All existing `test_domain_models.py` tests must pass
- New tests in `tests/unit/test_domain_models_edge.py` for new methods

---

### 2B. Decompose PlanActFlowConfig [F-011]

**File:** `weebot/application/models/plan_act_flow_config.py`

**Current state:** 22 parameters in a single dataclass.

**Change:** Split into focused sub-configs:

```python
@dataclass
class LLMConfig:
    """LLM-related configuration."""
    llm: LLMPort
    model: Optional[str] = None
    context_aware_model_selection: bool = True

@dataclass
class ToolConfig:
    """Tool-related configuration."""
    tools: ToolCollection
    max_steps: Optional[int] = None
    max_step_repetitions: int = DEFAULT_MAX_STEP_REPETITIONS

@dataclass
class SessionConfig:
    """Session and persistence configuration."""
    session: Session
    state_repo: Optional[StateRepositoryPort] = None
    event_bus: Optional[EventBusPort] = None
    mediator: Optional[Mediator] = None
    checkpoint_port: Optional[CheckpointPort] = None

@dataclass
class SkillConfig:
    """Skill and personality configuration."""
    skill_prompt: Optional[str] = None
    skill_retriever: Optional[SkillRetrieverPort] = None
    profile_name: Optional[str] = None
    personality = None
    agent_role: Optional[str] = None

@dataclass
class SafetyConfig:
    """Safety and review configuration."""
    truth_binder: Optional[TruthBinder] = None
    plan_critic: Optional[PlanCriticService] = None
    code_reviewer: Optional[Any] = None
    hooks: Optional[HookRegistry] = None

@dataclass
class PlanActFlowConfig:
    """Top-level config — composes sub-configs."""
    llm_config: LLMConfig
    tool_config: ToolConfig
    session_config: SessionConfig
    skill_config: SkillConfig = field(default_factory=SkillConfig)
    safety_config: SafetyConfig = field(default_factory=SafetyConfig)
    # Legacy fields for backward compatibility (deprecated)
    max_iterations: int = DEFAULT_MAX_FLOW_ITERATIONS
    auto_terminate_on_plan_complete: bool = True
    episodic_memory = None
    steering = None
    truth_binder = None  # moved to safety_config
    plan_critic = None   # moved to safety_config
    # ... etc
```

**Backward compatibility:** Keep the flat constructor working via `__init__` that maps flat params to sub-configs. All existing call sites continue to work unchanged. New code uses sub-configs.

**Impact:** Reduces coupling at the config nexus. Each sub-config is independently testable and evolveable.

**Validation:**
- All existing `test_plan_act_flow.py` tests must pass
- `PlanActFlowConfig(llm=..., tools=..., session=...)` flat construction must still work

---

### 2C. Decouple AgentRunner from Core Internals [F-010]

**File:** `weebot/interfaces/cli/agent_runner.py`

**Current state (lines 165-167):**
```python
from weebot.core.behavior_integration import start_session_tracking_async
behavior_tracker = await start_session_tracking_async(...)
```

**Change:** Inject behavior tracking via a port:

```python
# New port: application/ports/behavior_tracking_port.py
class BehaviorTrackingPort(ABC):
    @abstractmethod
    async def start_tracking(self, session_id: str, working_dir: Path, user_id: str) -> Optional[Any]: ...
    @abstractmethod
    async def stop_tracking(self, session_id: str, generate_report: bool = True) -> Optional[dict]: ...

# AgentRunner receives BehaviorTrackingPort via constructor
class AgentRunner:
    def __init__(self, ..., behavior_tracking: Optional[BehaviorTrackingPort] = None):
        self._behavior_tracking = behavior_tracking
```

**Impact:** Interface layer no longer reaches into core internals. Behavior tracking becomes a pluggable concern.

**Validation:**
- All `agent_runner.py` tests must pass
- CLI end-to-end test must pass

---

### Phase 2 Success Criteria

```bash
pytest tests/unit/test_domain_models_edge.py tests/unit/test_plan_act_flow.py tests/unit/test_agent_context.py -v
pytest tests/unit/test_architecture_fitness.py -v
python -m importlinter --config .importlinter
```

**Expected Score After Phase 2:** 9.3/10

---

## PHASE 3: PERSISTENCE MATURITY + LEGACY CLEANUP

**Target:** Eliminate F-008, F-012
**Score Impact:** 9.3 → 9.5 (+0.2)
**Effort:** 1 sprint (3-5 days)
**Risk:** LOW (mostly cleanup)

### 3A. Migrate EventStore to aiosqlite [F-008]

**File:** `weebot/infrastructure/event_store.py`

**Current state:** Uses sync `sqlite3` with `asyncio.to_thread` wrappers.

**Change:** Replace with `aiosqlite` for native async I/O:

```python
import aiosqlite

class EventStore(EventStorePort):
    def __init__(self, db_path: str = "~/.weebot/events.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path_str = str(self.db_path)

    async def _get_connection(self):
        conn = await aiosqlite.connect(self._db_path_str)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
            await conn.commit()
        finally:
            await conn.close()

    async def log_event(self, session_id, event_type, data, cost=0.0, model="", tokens_used=0):
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO events (session_id, event_type, data_json, cost, model, tokens_used) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, event_type, json.dumps(data), cost, model, tokens_used),
            )
            await conn.execute(
                "UPDATE sessions SET total_cost = total_cost + ?, total_tokens = total_tokens + ? WHERE id = ?",
                (cost, tokens_used, session_id),
            )
            return cursor.lastrowid
```

**Impact:** True async I/O without thread pool overhead. Consistent with `SQLiteToolRepository` and `SQLiteCheckpointStore` which already use `aiosqlite`.

**Validation:**
- All `test_event_store.py` tests must pass
- `test_architecture_fitness.py::test_no_blocking_calls_in_async` — remove EventStore from known exceptions

---

### 3B. Archive Legacy Frozen Modules [F-012]

**Files:** `weebot/core/agent.py`, `weebot/state_manager.py`, `weebot/ai_router.py`, `weebot/agent_core_v2.py`

**Action:**
1. Create `weebot/_legacy/` directory
2. Move frozen modules there with `__init__.py` re-exports for backward compatibility
3. Add `# DEPRECATED: Moved to _legacy/. Will be removed 2027-03-01.` headers
4. Update `weebot/__init__.py` lazy imports to point to `_legacy/`
5. Update `tests/unit/test_architecture_fitness.py::test_no_flat_files_at_root` allowed list

**Impact:** Cleans up `weebot/` root directory. Makes the architecture boundaries visually clear.

**Validation:**
- All existing tests must pass (re-exports preserve backward compat)
- `test_no_flat_files_at_root` must pass with updated allowed list

---

### 3C. Add Missing Architecture Fitness Tests

**File:** `tests/unit/test_architecture_fitness.py`

**Add new tests:**

```python
def test_event_bus_has_backpressure():
    """AsyncEventBus must have a semaphore for handler concurrency."""
    from weebot.infrastructure.event_bus import AsyncEventBus
    bus = AsyncEventBus()
    assert hasattr(bus, '_semaphore'), "AsyncEventBus must have _semaphore for backpressure"

def test_bash_tool_requires_sandbox_injection():
    """BashTool constructor must require sandbox parameter (no DI fallback)."""
    import inspect
    from weebot.tools.bash_tool import BashTool
    sig = inspect.signature(BashTool.__init__)
    params = list(sig.parameters.keys())
    assert 'sandbox' in params, "BashTool must accept sandbox parameter"
    # Verify no default value (required parameter)
    sandbox_param = sig.parameters['sandbox']
    assert sandbox_param.default is inspect.Parameter.empty, (
        "BashTool.sandbox must be required (no default)"
    )

def test_event_store_uses_async_driver():
    """EventStore must use aiosqlite, not sync sqlite3."""
    from weebot.infrastructure.event_store import EventStore
    import inspect
    source = inspect.getsource(EventStore)
    assert 'aiosqlite' in source or 'to_thread' not in source, (
        "EventStore should use aiosqlite, not asyncio.to_thread with sync sqlite3"
    )
```

**Validation:**
- `pytest tests/unit/test_architecture_fitness.py -v` — all tests pass

---

### Phase 3 Success Criteria

```bash
pytest tests/unit/test_event_store.py tests/unit/test_architecture_fitness.py -v
python -m importlinter --config .importlinter
```

**Expected Score After Phase 3:** 9.5/10

---

## PHASE 4: ENFORCEMENT MATURITY (Score 9.5 → 9.5+)

**Target:** Close the remaining 0.5 gap between "consistent patterns" (9) and "observable, testable, scalable" (10)
**Score Impact:** 9.5 → 9.7
**Effort:** Ongoing (not a single sprint)
**Risk:** LOW

### 4A. Strengthen Import Linter Contracts

**File:** `.importlinter`

**Add contract:**
```ini
[importlinter:contract:no-legacy-imports]
name = Production code must not import legacy modules
type = forbidden
source_modules = weebot.application
                 weebot.infrastructure
                 weebot.interfaces
forbidden_modules = weebot._legacy
ignore_imports = weebot.application.di._factories -> weebot._legacy
```

### 4B. Add Architecture Fitness Test for Config Complexity

```python
def test_plan_act_flow_config_param_count():
    """PlanActFlowConfig must not exceed 15 top-level parameters."""
    from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
    import dataclasses
    fields = dataclasses.fields(PlanActFlowConfig)
    assert len(fields) <= 15, (
        f"PlanActFlowConfig has {len(fields)} parameters — "
        f"decompose into sub-configs (max 15)"
    )
```

### 4C. Add Prometheus Metrics for Architecture Health

```python
# In infrastructure/observability/metrics.py
event_bus_handler_duration = Histogram(
    'weebot_event_bus_handler_duration_seconds',
    'Time spent in event bus handler',
    ['handler_name'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)
event_bus_handler_errors = Counter(
    'weebot_event_bus_handler_errors_total',
    'Event bus handler errors',
    ['handler_name', 'error_type'],
)
```

---

## IMPLEMENTATION SEQUENCING

```
Phase 1 (Sprint 1): Event System + Coupling Fixes
  ├── 1A: AsyncEventBus backpressure          (2 days)
  ├── 1B: EventBroker → AsyncEventBus         (2 days)
  ├── 1C: PlanActFlow agent imports            (0.5 day)
  ├── 1D: core/agent.py legacy archive         (0.5 day)
  ├── 1E: BashTool DI fix                      (0.5 day)
  ├── 1F: MCP server DI fix                    (0.5 day)
  └── 1G: Dead code removal                    (0.5 day)
  
Phase 2 (Sprint 2): Domain + Config
  ├── 2A: Enrich domain models                 (2 days)
  ├── 2B: PlanActFlowConfig decomposition      (2 days)
  └── 2C: AgentRunner decoupling               (1 day)

Phase 3 (Sprint 3): Persistence + Cleanup
  ├── 3A: EventStore aiosqlite migration       (1 day)
  ├── 3B: Legacy module archival               (1 day)
  └── 3C: New fitness tests                    (1 day)

Phase 4 (Ongoing): Enforcement
  ├── 4A: Import linter contracts              (0.5 day)
  ├── 4B: Config complexity test               (0.5 day)
  └── 4C: Prometheus metrics                   (1 day)
```

---

## RISK MITIGATION

| Risk | Mitigation | Rollback |
|------|-----------|----------|
| EventBroker migration breaks AgentContext | Contract tests + backward compat wrapper | Revert EventBroker to self-contained |
| PlanActFlowConfig decomposition breaks callers | Keep flat constructor working | Revert to single dataclass |
| BashTool sandbox requirement breaks tests | Update test fixtures first | Add optional default back |
| Legacy archival breaks imports | Re-export from `_legacy/__init__.py` | Move files back |

---

## POST-REFACTOR VALIDATION CHECKLIST

```bash
# 1. Architecture fitness tests (must be 0 failures)
pytest tests/unit/test_architecture_fitness.py -v

# 2. Import linter (must pass all contracts)
python -m importlinter --config .importlinter

# 3. Port contract tests (must have adapters for all ports)
pytest tests/unit/test_port_contracts.py -v

# 4. Full unit test suite
pytest tests/unit/ -v --tb=short

# 5. Integration tests
pytest tests/integration/ -v --tb=short

# 6. No blocking calls in async
pytest tests/unit/test_architecture_fitness.py::test_no_blocking_calls_in_async -v

# 7. No settings imports in tools
pytest tests/unit/test_architecture_fitness.py::test_no_settings_import_in_tools -v

# 8. Domain purity
pytest tests/unit/test_architecture_fitness.py::test_domain_has_no_outer_imports -v
```

---

## EXPECTED OUTCOME

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Architecture Score | 8.0 | 9.5 | +1.5 |
| MEDIUM findings | 4 | 0 | -4 |
| LOW findings | 6 | 1 (F-012 partial) | -5 |
| Event systems | 2 (dual) | 1 (unified) | -1 |
| Config parameters | 22 | 15 (sub-configs) | -7 |
| Legacy modules at root | 4 | 0 (archived) | -4 |
| Architecture fitness tests | 19 | 22 | +3 |
| Import linter contracts | 4 | 5 | +1 |
